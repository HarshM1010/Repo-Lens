import urllib.parse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, Http404
from django.utils import timezone
from django.db.models import Q
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Repository, AnalysisJob, AnalysisReport
from .serializers import RepositorySerializer, AnalysisJobSerializer, AnalysisReportSerializer
from .tasks import start_analysis_flow
from repolens.celery import app as celery_app


# =====================================================================
# SESSION TEMPLATE VIEWS (For Django HTML Templates & Session Auth)
# =====================================================================

@login_required
def dashboard_view(request):
    """
    Renders the central system metrics dashboard.
    """
    user_repos = Repository.objects.filter(user=request.user)
    user_jobs = AnalysisJob.objects.filter(repository__user=request.user)
    
    # System wide metrics (scoped to user for privacy)
    total_analyzed = user_repos.count()
    running_jobs = user_jobs.filter(status='RUNNING').count()
    completed_jobs = user_jobs.filter(status='COMPLETED').count()
    failed_jobs = user_jobs.filter(status='FAILED').count()
    queue_length = user_jobs.filter(status='PENDING').count()
    
    # Worker Status
    worker_status = "Inactive"
    try:
        inspect = celery_app.control.inspect()
        active = inspect.active()
        if active:
            worker_status = f"Active ({len(active)} worker node(s))"
        else:
            worker_status = "No active workers"
    except Exception:
        worker_status = "Celery worker offline"

    # Average Runtime
    completed_jobs_list = user_jobs.filter(status='COMPLETED', end_time__isnull=False)
    durations = [j.duration_seconds() for j in completed_jobs_list]
    avg_runtime = round(sum(durations) / len(durations), 1) if durations else 0.0

    recent_jobs = user_jobs.order_by('-start_time')[:10]

    context = {
        'total_analyzed': total_analyzed,
        'running_jobs': running_jobs,
        'completed_jobs': completed_jobs,
        'failed_jobs': failed_jobs,
        'queue_length': queue_length,
        'worker_status': worker_status,
        'avg_runtime': avg_runtime,
        'recent_jobs': recent_jobs,
    }
    return render(request, 'analysis/dashboard.html', context)


@login_required
def analysis_new_view(request):
    """
    Renders the submit repo form and starts analysis job.
    """
    if request.method == 'POST':
        url = request.POST.get('url', '').strip()
        if not url:
            messages.error(request, "Repository URL cannot be empty.")
            return render(request, 'analysis/analysis_new.html')

        # Clean/parse owner and name
        # Examples: https://github.com/django/django or git@github.com:django/django.git
        name = url.rstrip('/').split('/')[-1]
        if name.endswith('.git'):
            name = name[:-4]
            
        owner = "github"
        parts = url.rstrip('/').split('/')
        if len(parts) >= 2:
            owner = parts[-2]
            
        repo_name = f"{owner}/{name}"

        # Create or fetch repo
        repo, created = Repository.objects.get_or_create(
            user=request.user,
            url=url,
            defaults={'name': repo_name}
        )

        # Create new Job
        job = AnalysisJob.objects.create(
            repository=repo,
            status='PENDING',
            current_stage='PENDING',
            progress=0
        )

        # Trigger Celery Task Pipeline
        start_analysis_flow.delay(str(job.id))
        
        messages.success(request, f"Analysis job scheduled for {repo_name}!")
        return redirect('job_details', job_id=job.id)

    return render(request, 'analysis/analysis_new.html')


@login_required
def job_details_view(request, job_id):
    """
    Shows real-time analysis progress using WebSockets.
    """
    job = get_object_or_404(AnalysisJob, id=job_id, repository__user=request.user)
    return render(request, 'analysis/job_details.html', {'job': job})


@login_required
def analysis_detail_view(request, job_id):
    """
    Displays the completed code metrics, graph, security scans, and AI report.
    """
    job = get_object_or_404(AnalysisJob, id=job_id, repository__user=request.user)
    if job.status != 'COMPLETED' or not hasattr(job, 'report'):
        messages.warning(request, "The analysis job is not complete yet.")
        return redirect('job_details', job_id=job.id)
        
    report = job.report
    
    import markdown
    ai_doc_html = markdown.markdown(report.ai_documentation or "")
    
    context = {
        'job': job,
        'report': report,
        'project_summary': report.project_summary,
        'dependency_list': report.dependency_list,
        'static_metrics': report.static_metrics,
        'security_report': report.security_report,
        'dependency_graph': report.dependency_graph,
        'ai_documentation_html': ai_doc_html,
    }
    return render(request, 'analysis/analysis_detail.html', context)


@login_required
def analysis_history_view(request):
    """
    Displays historical jobs with searching, sorting, and filtering.
    """
    query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    lang_filter = request.GET.get('lang', '')
    sort_by = request.GET.get('sort', '-start_time')

    jobs = AnalysisJob.objects.filter(repository__user=request.user)

    if query:
        jobs = jobs.filter(
            Q(repository__name__icontains=query) | 
            Q(repository__url__icontains=query) |
            Q(commit_hash__icontains=query)
        )

    if status_filter:
        jobs = jobs.filter(status=status_filter)

    if lang_filter:
        jobs = jobs.filter(report__language__iexact=lang_filter)

    # Validate sorting options
    valid_sorts = ['start_time', '-start_time', 'repository__name', '-repository__name', 'progress', '-progress']
    if sort_by not in valid_sorts:
        sort_by = '-start_time'

    jobs = jobs.order_by(sort_by)

    # Get distinct languages for filters
    languages = AnalysisReport.objects.filter(job__repository__user=request.user).values_list('language', flat=True).distinct()

    context = {
        'jobs': jobs,
        'query': query,
        'status_filter': status_filter,
        'lang_filter': lang_filter,
        'sort_by': sort_by,
        'languages': languages,
    }
    return render(request, 'analysis/analysis_history.html', context)


@login_required
def reanalyze_view(request, job_id):
    """
    Triggers re-analysis for an existing repository (creates a new Job).
    """
    old_job = get_object_or_404(AnalysisJob, id=job_id, repository__user=request.user)
    
    # Create new Job for same repository
    job = AnalysisJob.objects.create(
        repository=old_job.repository,
        status='PENDING',
        current_stage='PENDING',
        progress=0
    )

    # Trigger Celery Task Pipeline
    start_analysis_flow.delay(str(job.id))
    
    messages.success(request, f"Re-analysis scheduled for {old_job.repository.name}!")
    return redirect('job_details', job_id=job.id)


@login_required
def delete_analysis_view(request, job_id):
    """
    Deletes the analysis job.
    """
    job = get_object_or_404(AnalysisJob, id=job_id, repository__user=request.user)
    repo_name = job.repository.name
    job.delete()
    messages.success(request, f"Analysis record for {repo_name} deleted successfully.")
    return redirect('analysis_history')


@login_required
def download_markdown_view(request, job_id):
    """
    Downloads AI generated markdown report as a file.
    """
    job = get_object_or_404(AnalysisJob, id=job_id, repository__user=request.user)
    if not hasattr(job, 'report') or not job.report.ai_documentation:
        raise Http404("Documentation not available.")

    content = job.report.ai_documentation
    filename = f"RepoLens_Doc_{job.repository.name.replace('/', '_')}_{job.commit_hash[:7]}.md"
    
    response = HttpResponse(content, content_type='text/markdown')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# =====================================================================
# REST API VIEWSETS (For Simple-JWT Authenticated API Clients)
# =====================================================================

class RepositoryViewSet(viewsets.ModelViewSet):
    serializer_class = RepositorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Repository.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AnalysisJobViewSet(viewsets.ModelViewSet):
    serializer_class = AnalysisJobSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AnalysisJob.objects.filter(repository__user=self.request.user)

    def perform_create(self, serializer):
        # Requires repository_id in POST body
        repo_id = self.request.data.get('repository')
        repo = get_object_or_404(Repository, id=repo_id, user=self.request.user)
        job = serializer.save(repository=repo)
        
        # Trigger Celery Pipeline
        start_analysis_flow.delay(str(job.id))

    @action(detail=True, methods=['post'])
    def reanalyze(self, request, pk=None):
        old_job = self.get_object()
        job = AnalysisJob.objects.create(
            repository=old_job.repository,
            status='PENDING',
            current_stage='PENDING',
            progress=0
        )
        start_analysis_flow.delay(str(job.id))
        serializer = self.get_serializer(job)
        return Response(serializer.data)


class AnalysisReportViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AnalysisReportSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AnalysisReport.objects.filter(job__repository__user=self.request.user)
