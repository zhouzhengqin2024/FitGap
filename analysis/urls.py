from django.urls import path

from . import views

app_name = 'analysis'

urlpatterns = [
    path('', views.landing_view, name='landing'),
    path('analyse/', views.input_view, name='input'),
    path('account/', views.account_entry_view, name='account_entry'),
    path('extract-document-text/', views.extract_document_text_view, name='extract_document_text'),
    path('results/ai-prioritise/', views.ai_prioritise_view, name='ai_prioritise'),
    path('results/ai-results/', views.ai_results_view, name='ai_results'),
    path('results/ai-learning-roadmap/', views.ai_learning_roadmap_view, name='ai_learning_roadmap'),
    path('results/learning-roadmap/', views.learning_roadmap_view, name='learning_roadmap'),
    path('results/full-analysis/', views.full_analysis_view, name='full_analysis'),
]
