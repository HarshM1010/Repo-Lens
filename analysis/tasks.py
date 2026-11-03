import os
import shutil
import tempfile
import zipfile
from celery import Celery, shared_task, chord
from django.conf import settings
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import boto3

from .models import Repository, AnalysisJob, AnalysisReport
from . import analyzer

def update_job_progress(job_id, stage, progress, status='RUNNING', error_message=None):
    """
    Helper to update job status, progress percentage, and notify client via WebSocket.
    """
    try:
        job = AnalysisJob.objects.get(id=job_id)
        job.status = status
        job.current_stage = stage
        job.progress = progress
        if error_message:
            job.error_message = error_message
        if status in ['COMPLETED', 'FAILED']:
            job.end_time = timezone.now()
        job.save()

        # Notify via channels
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"job_{job.id}",
                {
                    "type": "job.update",
                    "data": {
                        "job_id": str(job.id),
                        "status": job.status,
                        "stage": job.get_current_stage_display(),
                        "progress": job.progress,
                        "stage_key": job.current_stage,
                        "error_message": job.error_message or "",
                        "retry_count": job.retry_count,
                        "duration": job.duration_seconds()
                    }
                }
            )
            # Update dashboard stats
            async_to_sync(channel_layer.group_send)(
                "dashboard_stats",
                {
                    "type": "stats.update",
                    "data": {
                        "action": "refresh"
                    }
                }
            )
    except Exception as e:
        print(f"Error updating job progress: {e}")


def upload_zip_to_minio(repo_path, job_id):
    """
    Compresses the repository into a zip archive and uploads it to MinIO storage.
    """
    try:
        temp_dir = tempfile.gettempdir()
        zip_path = os.path.join(temp_dir, f"{job_id}.zip")
        
        # Zip repository files
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(repo_path):
                if '.git' in root.split(os.sep):
                    continue
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, repo_path)
                    zipf.write(full_path, rel_path)
                    
        # Upload using boto3
        s3 = boto3.client(
            's3',
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
        )
        
        # Ensure bucket exists
        try:
            s3.create_bucket(Bucket=settings.MINIO_BUCKET_NAME)
        except Exception:
            pass  # Already exists or standard error
            
        object_name = f"archives/{job_id}.zip"
        s3.upload_file(zip_path, settings.MINIO_BUCKET_NAME, object_name)
        
        # Cleanup local zip
        if os.path.exists(zip_path):
            os.remove(zip_path)
            
        return f"{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET_NAME}/{object_name}"
    except Exception as e:
        print(f"MinIO archive upload warning: {e}")
        return None


@shared_task(bind=True, name="analysis.tasks.start_analysis_flow")
def start_analysis_flow(self, job_id):
    """
    Entrypoint task. Checks caching and sets up Celery Chord.
    """
    try:
        job = AnalysisJob.objects.get(id=job_id)
        job.worker_assigned = self.request.hostname or 'unknown_worker'
        job.save()
        
        update_job_progress(job_id, 'PENDING', 5)
        
        # 1. Fetch remote commit hash without cloning
        repo_url = job.repository.url
        commit_hash = analyzer.get_remote_commit_hash(repo_url)
        
        if not commit_hash:
            raise ValueError("Failed to fetch remote repository details. Verify the repository URL is public and valid.")
            
        job.commit_hash = commit_hash
        job.save()
        
        # 2. Repository Caching Check
        # Check if we have already completed analysis on this repository with the same commit hash
        cached_job = AnalysisJob.objects.filter(
            repository__url=repo_url,
            commit_hash=commit_hash,
            status='COMPLETED'
        ).exclude(id=job.id).first()
        
        if cached_job and hasattr(cached_job, 'report'):
            # Reuse cached report
            cached_report = cached_job.report
            AnalysisReport.objects.create(
                job=job,
                language=cached_report.language,
                project_summary=cached_report.project_summary,
                dependency_list=cached_report.dependency_list,
                static_metrics=cached_report.static_metrics,
                security_report=cached_report.security_report,
                dependency_graph=cached_report.dependency_graph,
                ai_documentation=cached_report.ai_documentation,
                minio_archive_path=cached_report.minio_archive_path
            )
            update_job_progress(job_id, 'COMPLETED', 100, status='COMPLETED')
            return f"Cached analysis reused from job {cached_job.id}"

        # 3. Clone Repository
        # Determine temporary directory path
        repo_dir = os.path.join(tempfile.gettempdir(), 'repolens', str(job.id))
        update_job_progress(job_id, 'CLONE', 15)
        analyzer.clone_repo(repo_url, repo_dir)
        update_job_progress(job_id, 'DETECT_LANGUAGE', 25)
        
        # 4. Trigger Parallel Chord header tasks
        # These execute concurrently.
        header = [
            detect_language_task.subtask(args=(job_id, repo_dir)),
            analyze_structure_task.subtask(args=(job_id, repo_dir)),
            analyze_dependencies_task.subtask(args=(job_id, repo_dir)),
            calculate_metrics_task.subtask(args=(job_id, repo_dir)),
            security_scan_task.subtask(args=(job_id, repo_dir)),
            generate_dependency_graph_task.subtask(args=(job_id, repo_dir)),
        ]
        
        # Callback to synthesize results and finalize
        callback = finalize_analysis_callback.subtask(args=(job_id, repo_dir))
        
        chord(header)(callback)
        
    except Exception as e:
        update_job_progress(job_id, 'FAILED', 100, status='FAILED', error_message=str(e))
        raise e


@shared_task(name="analysis.tasks.detect_language_task")
def detect_language_task(job_id, repo_path):
    """Task: Detect primary codebase language."""
    try:
        primary, break_down = analyzer.detect_languages(repo_path)
        return {'task': 'detect_language', 'primary': primary, 'percentages': break_down}
    except Exception as e:
        return {'task': 'detect_language', 'error': str(e)}


@shared_task(name="analysis.tasks.analyze_structure_task")
def analyze_structure_task(job_id, repo_path):
    """Task: Analyze folder directories and sizes."""
    try:
        res = analyzer.analyze_structure(repo_path)
        return {'task': 'analyze_structure', 'data': res}
    except Exception as e:
        return {'task': 'analyze_structure', 'error': str(e)}


@shared_task(name="analysis.tasks.analyze_dependencies_task")
def analyze_dependencies_task(job_id, repo_path):
    """Task: Extract project dependency package lists."""
    try:
        deps = analyzer.analyze_dependencies(repo_path)
        return {'task': 'analyze_dependencies', 'data': deps}
    except Exception as e:
        return {'task': 'analyze_dependencies', 'error': str(e)}


@shared_task(name="analysis.tasks.calculate_metrics_task")
def calculate_metrics_task(job_id, repo_path):
    """Task: Compute cyclomatic complexity & LOC."""
    try:
        metrics = analyzer.calculate_metrics(repo_path)
        return {'task': 'calculate_metrics', 'data': metrics}
    except Exception as e:
        return {'task': 'calculate_metrics', 'error': str(e)}


@shared_task(name="analysis.tasks.security_scan_task")
def security_scan_task(job_id, repo_path):
    """Task: Run static security checks."""
    try:
        sec = analyzer.run_security_scan(repo_path)
        return {'task': 'security_scan', 'data': sec}
    except Exception as e:
        return {'task': 'security_scan', 'error': str(e)}


@shared_task(name="analysis.tasks.generate_dependency_graph_task")
def generate_dependency_graph_task(job_id, repo_path):
    """Task: Construct file dependency structures."""
    try:
        graph = analyzer.generate_dependency_graph(repo_path)
        return {'task': 'generate_dependency_graph', 'data': graph}
    except Exception as e:
        return {'task': 'generate_dependency_graph', 'error': str(e)}


@shared_task(name="analysis.tasks.finalize_analysis_callback")
def finalize_analysis_callback(results, job_id, repo_path):
    """
    Chord Callback: Run AI summary, upload zip to MinIO, and write final database report.
    """
    try:
        update_job_progress(job_id, 'AI_DOC', 80)
        
        # 1. Compile parallel result dicts
        compilation = {}
        for res in results:
            if not res or 'error' in res:
                continue
            compilation[res['task']] = res
            
        lang_data = compilation.get('detect_language', {})
        struct_data = compilation.get('analyze_structure', {}).get('data', {})
        deps_list = compilation.get('analyze_dependencies', {}).get('data', [])
        metrics_data = compilation.get('calculate_metrics', {}).get('data', {})
        security_data = compilation.get('security_scan', {}).get('data', {})
        graph_data = compilation.get('generate_dependency_graph', {}).get('data', {})
        
        # 2. Generate AI report using Gemini or Fallback Heuristics
        job = AnalysisJob.objects.get(id=job_id)
        language = lang_data.get('primary', 'Unknown')
        
        update_job_progress(job_id, 'AI_DOC', 85)
        ai_doc = analyzer.generate_ai_documentation(
            repo_name=job.repository.name,
            language=language,
            summary=struct_data,
            metrics=metrics_data,
            security=security_data,
            gemini_api_key=settings.GEMINI_API_KEY
        )
        
        # 3. Zip files & Upload to MinIO
        update_job_progress(job_id, 'FINALIZING', 90)
        archive_path = upload_zip_to_minio(repo_path, job_id)
        
        # 4. Save report in DB
        report = AnalysisReport.objects.create(
            job=job,
            language=language,
            project_summary={
                'percentages': lang_data.get('percentages', {}),
                'total_files': struct_data.get('total_files', 0),
                'total_size_human': struct_data.get('total_size_human', '0 B'),
                'structure': struct_data.get('structure', {})
            },
            dependency_list=deps_list,
            static_metrics=metrics_data,
            security_report=security_data,
            dependency_graph=graph_data,
            ai_documentation=ai_doc,
            minio_archive_path=archive_path
        )
        
        # 5. Clean up temporary directory
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
            
        # 6. Complete Job
        update_job_progress(job_id, 'COMPLETED', 100, status='COMPLETED')
        return f"Report successfully stored for job {job_id}"
        
    except Exception as e:
        # Cleanup on failure
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
        update_job_progress(job_id, 'FAILED', 100, status='FAILED', error_message=str(e))
        raise e
