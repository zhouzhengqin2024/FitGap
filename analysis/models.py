from django.conf import settings
from django.db import models


class AnalysisRecord(models.Model):
    STATUS_STARTED = 'started'
    STATUS_ANALYSIS_COMPLETED = 'analysis_completed'
    STATUS_PRIORITIES_COMPLETED = 'priorities_completed'
    STATUS_ROADMAP_COMPLETED = 'roadmap_completed'

    STATUS_CHOICES = [
        (STATUS_STARTED, 'Started'),
        (STATUS_ANALYSIS_COMPLETED, 'Analysis completed'),
        (STATUS_PRIORITIES_COMPLETED, 'Priorities completed'),
        (STATUS_ROADMAP_COMPLETED, 'Roadmap completed'),
    ]

    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('zh', 'Simplified Chinese'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='analysis_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default='en')
    target_role = models.CharField(max_length=255, default='Untitled Analysis')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_STARTED)
    analysis_snapshot = models.JSONField(default=dict, blank=True)
    priority_snapshot = models.JSONField(default=dict, blank=True)
    roadmap_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.target_role} ({self.user})'
