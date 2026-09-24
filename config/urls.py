from django.contrib import admin
from django.urls import path

from accounts.views import BaselineLoginView, BaselineLogoutView, signup
from school.views import create_assignment, create_exam_result, dashboard, home


admin.site.site_header = "AuthShield 360 administration"
admin.site.site_title = "AuthShield 360"
admin.site.index_title = "Fictional school data"

urlpatterns = [
    path("", home, name="home"),
    path("signup/", signup, name="signup"),
    path("login/", BaselineLoginView.as_view(), name="login"),
    path("logout/", BaselineLogoutView.as_view(), name="logout"),
    path("dashboard/", dashboard, name="dashboard"),
    path("teacher/assignments/new/", create_assignment, name="create_assignment"),
    path("teacher/results/new/", create_exam_result, name="create_exam_result"),
    path("admin/", admin.site.urls),
]
