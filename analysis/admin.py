from django.contrib import admin
from .models import Repository, AnalysisJob, AnalysisReport


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'url', 'created_at')
    search_fields = ('name', 'url', 'user__username')
    list_filter = ('created_at',)


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'repository', 'status', 'current_stage', 'progress', 'start_time', 'duration_seconds')
    list_filter = ('status', 'current_stage', 'start_time')
    search_fields = ('id', 'repository__name', 'commit_hash')
    readonly_fields = ('start_time', 'end_time')

    def duration_seconds(self, obj):
        return obj.duration_seconds()
    duration_seconds.short_description = 'Duration (s)'


@admin.register(AnalysisReport)
class AnalysisReportAdmin(admin.ModelAdmin):
    list_display = ('job', 'language', 'created_at')
    list_filter = ('language', 'created_at')
    search_fields = ('job__id', 'job__repository__name')
