from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Repository, AnalysisJob, AnalysisReport


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']


class RepositorySerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Repository
        fields = ['id', 'user', 'url', 'name', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'name', 'description', 'created_at', 'updated_at']


class AnalysisReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisReport
        fields = [
            'id', 'language', 'project_summary', 'dependency_list',
            'static_metrics', 'security_report', 'dependency_graph',
            'ai_documentation', 'minio_archive_path', 'created_at'
        ]


class AnalysisJobSerializer(serializers.ModelSerializer):
    repository = RepositorySerializer(read_only=True)
    report = AnalysisReportSerializer(read_only=True)
    duration = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisJob
        fields = [
            'id', 'repository', 'status', 'current_stage', 'progress',
            'commit_hash', 'start_time', 'end_time', 'worker_assigned',
            'retry_count', 'error_message', 'duration', 'report'
        ]

    def get_duration(self, obj):
        return obj.duration_seconds()
