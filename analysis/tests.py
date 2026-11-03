from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from .models import Repository, AnalysisJob, AnalysisReport
from .tasks import update_job_progress, start_analysis_flow
from . import analyzer


class RepoLensTestCase(TestCase):
    def setUp(self):
        # Create test users
        self.user = User.objects.create_user(username='testuser', password='testpassword123', email='test@repolens.com')
        self.other_user = User.objects.create_user(username='otheruser', password='otherpassword123')
        
        # Setup API clients
        self.client = APIClient()
        self.session_client = APIClient()
        self.session_client.login(username='testuser', password='testpassword123')

        # Create base test Repository
        self.repo = Repository.objects.create(
            user=self.user,
            url='https://github.com/pallets/click',
            name='pallets/click'
        )

    def test_repository_creation(self):
        """Verify models setup and foreign keys."""
        self.assertEqual(self.repo.name, 'pallets/click')
        self.assertEqual(self.repo.user.username, 'testuser')

    def test_job_and_report_relations(self):
        """Verify Job stages, statuses, and OneToOne report connection."""
        job = AnalysisJob.objects.create(
            repository=self.repo,
            status='PENDING',
            current_stage='PENDING',
            progress=0
        )
        self.assertIsNotNone(job.id)
        
        report = AnalysisReport.objects.create(
            job=job,
            language='Python',
            project_summary={'total_files': 10},
            dependency_list=[],
            static_metrics={'loc': 1500},
            security_report={'security_score': 100},
            dependency_graph={'nodes': [], 'edges': []},
            ai_documentation='# Click docs'
        )
        self.assertEqual(job.report.language, 'Python')
        self.assertEqual(job.report.static_metrics['loc'], 1500)

    def test_dashboard_login_required(self):
        """Verify dashboard requires session authentication."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)  # Redirects to login

        response = self.session_client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_rest_api_jwt_auth(self):
        """Verify REST API calls reject unauthenticated requests and accept valid JWT."""
        # Retrieve JWT Token
        url = reverse('token_obtain_pair')
        response = self.client.post(url, {'username': 'testuser', 'password': 'testpassword123'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access_token = response.data['access']

        # Call Repository API list endpoint
        repo_url = reverse('api-repository-list')
        response = self.client.get(repo_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticate with token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        response = self.client.get(repo_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_caching_and_flow(self):
        """
        Verify that start_analysis_flow can reuse a completed analysis report
        for the same commit hash without cloning.
        """
        # Create an existing completed job and report
        job_old = AnalysisJob.objects.create(
            repository=self.repo,
            status='COMPLETED',
            current_stage='COMPLETED',
            progress=100,
            commit_hash='abcdef1234567890abcdef1234567890123456'
        )
        report_old = AnalysisReport.objects.create(
            job=job_old,
            language='Python',
            project_summary={'total_files': 42},
            static_metrics={'loc': 5000},
            security_report={'security_score': 95},
            ai_documentation='# Cached report docs'
        )

        # Create a new job requesting analysis on the same repository
        job_new = AnalysisJob.objects.create(
            repository=self.repo,
            status='PENDING',
            current_stage='PENDING',
            progress=0
        )

        # Mock remote commit check to return the same hash
        original_commit_hash = analyzer.get_remote_commit_hash
        analyzer.get_remote_commit_hash = lambda url: 'abcdef1234567890abcdef1234567890123456'

        try:
            # Trigger analysis flow in Celery eager mode
            start_analysis_flow(str(job_new.id))
            
            # Refresh job from DB
            job_new.refresh_from_db()
            self.assertEqual(job_new.status, 'COMPLETED')
            self.assertEqual(job_new.report.language, 'Python')
            self.assertEqual(job_new.report.static_metrics['loc'], 5000)
            self.assertEqual(job_new.report.ai_documentation, '# Cached report docs')
            
        finally:
            analyzer.get_remote_commit_hash = original_commit_hash
