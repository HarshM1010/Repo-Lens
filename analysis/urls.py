from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register('api/repositories', views.RepositoryViewSet, basename='api-repository')
router.register('api/jobs', views.AnalysisJobViewSet, basename='api-job')
router.register('api/reports', views.AnalysisReportViewSet, basename='api-report')

urlpatterns = [
    # Dashboard and Front UI
    path('', views.dashboard_view, name='dashboard'),
    path('analysis/new/', views.analysis_new_view, name='analysis_new'),
    path('jobs/<uuid:job_id>/', views.job_details_view, name='job_details'),
    path('reports/<uuid:job_id>/', views.analysis_detail_view, name='analysis_detail'),
    path('history/', views.analysis_history_view, name='analysis_history'),
    path('reanalyze/<uuid:job_id>/', views.reanalyze_view, name='reanalyze'),
    path('delete/<uuid:job_id>/', views.delete_analysis_view, name='delete_analysis'),
    path('download/<uuid:job_id>/', views.download_markdown_view, name='download_markdown'),
    
    # Include REST API endpoints
    path('', include(router.urls)),
]
