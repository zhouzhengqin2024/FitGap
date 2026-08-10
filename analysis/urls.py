from django.urls import path

from . import views

app_name = 'analysis'

urlpatterns = [
    path('', views.input_view, name='input'),
    path('extract-document-text/', views.extract_document_text_view, name='extract_document_text'),
    path('results/ai-prioritise/', views.ai_prioritise_view, name='ai_prioritise'),
    path('results/ai-results/', views.ai_results_view, name='ai_results'),
    path('results/full-analysis/', views.full_analysis_view, name='full_analysis'),
]
