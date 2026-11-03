from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/jobs/(?P<job_id>[a-f0-9\-]+)/$', consumers.JobProgressConsumer.as_asgi()),
    re_path(r'^ws/dashboard/$', consumers.DashboardStatsConsumer.as_asgi()),
]
