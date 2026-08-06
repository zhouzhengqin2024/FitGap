from django.urls import path

from . import views

app_name = 'analysis'

urlpatterns = [
    path('', views.input_view, name='input'),
    path('extract-document-text/', views.extract_document_text_view, name='extract_document_text'),
]
