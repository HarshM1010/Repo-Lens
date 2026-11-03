import uuid
from django.db import models
from django.contrib.auth.models import User


class Repository(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='repositories')
    url = models.URLField(max_length=500)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Repositories"
        unique_together = ('user', 'url')

    def __str__(self):
        return f"{self.user.username} / {self.name}"


class AnalysisJob(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('RUNNING', 'Running'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    STAGE_CHOICES = [
        ('PENDING', 'Pending'),
        ('CLONE', 'Cloning Repository'),
        ('DETECT_LANGUAGE', 'Detecting Language'),
        ('STRUCTURE', 'Analyzing Project Structure'),
        ('DEPENDENCIES', 'Parsing Dependencies'),
        ('METRICS', 'Calculating Static Metrics'),
        ('SECURITY', 'Scanning Security Issues'),
        ('GRAPH', 'Generating Dependency Graph'),
        ('AI_DOC', 'Generating AI Documentation'),
        ('FINALIZING', 'Finalizing Storage'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='jobs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    current_stage = models.CharField(max_length=30, choices=STAGE_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0)  # 0 to 100
    commit_hash = models.CharField(max_length=100, blank=True, null=True)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    worker_assigned = models.CharField(max_length=255, blank=True, null=True)
    retry_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, null=True)

    def duration_seconds(self):
        if self.end_time:
            return round((self.end_time - self.start_time).total_seconds(), 2)
        import django.utils.timezone as timezone
        return round((timezone.now() - self.start_time).total_seconds(), 2)

    def __str__(self):
        return f"Job {self.id} - {self.repository.name} [{self.status}]"


class AnalysisReport(models.Model):
    job = models.OneToOneField(AnalysisJob, on_delete=models.CASCADE, related_name='report')
    language = models.CharField(max_length=100, default='Unknown')
    project_summary = models.JSONField(default=dict)
    dependency_list = models.JSONField(default=list)
    static_metrics = models.JSONField(default=dict)
    security_report = models.JSONField(default=dict)
    dependency_graph = models.JSONField(default=dict)
    ai_documentation = models.TextField(blank=True, null=True)
    minio_archive_path = models.CharField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for {self.job.repository.name} (Job: {self.job.id})"
