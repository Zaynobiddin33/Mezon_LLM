from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sorovlar/", views.request_list, name="requests"),
    path("sorovlar/<int:pk>/", views.review, name="review"),
    path("sorovlar/<int:pk>/tahlil/", views.analyze, name="analyze"),
    path("sorovlar/<int:pk>/suhbat/", views.chat, name="chat"),
    path("sorovlar/<int:pk>/qaror/", views.decide, name="decide"),
    path("hujjatlar/<int:pk>/", views.document_download, name="document_download"),
]
