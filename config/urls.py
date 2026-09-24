from django.contrib import admin
from django.urls import path

from accounts.views import BaselineLoginView, BaselineLogoutView, registration_status, signup
from school.admin_views import (
    admin_management,
    change_account_access,
    delete_school_account,
    review_account_request,
    review_enrollment_request,
)
from school.teacher_views import (
    create_assignment,
    create_exam_result,
    edit_assigned_student,
    request_enrollment_change,
    teacher_students,
)
from school.views import dashboard, home


admin.site.site_header = "AuthShield 360 administration"
admin.site.site_title = "AuthShield 360"
admin.site.index_title = "Fictional school data"

urlpatterns = [
    path("", home, name="home"),
    path("signup/", signup, {"role": "student"}, name="signup"),
    path("signup/student/", signup, {"role": "student"}, name="student_signup"),
    path("signup/teacher/", signup, {"role": "teacher"}, name="teacher_signup"),
    path("signup/status/", registration_status, name="registration_status"),
    path("login/", BaselineLoginView.as_view(), name="login"),
    path("logout/", BaselineLogoutView.as_view(), name="logout"),
    path("dashboard/", dashboard, name="dashboard"),
    path("teacher/assignments/new/", create_assignment, name="create_assignment"),
    path("teacher/results/new/", create_exam_result, name="create_exam_result"),
    path("teacher/students/", teacher_students, name="teacher_students"),
    path("teacher/students/<int:student_id>/edit/", edit_assigned_student, name="edit_assigned_student"),
    path("teacher/enrollment-requests/new/", request_enrollment_change, name="request_enrollment_change"),
    path("administrator/management/", admin_management, name="admin_management"),
    path("administrator/accounts/<int:user_id>/review/", review_account_request, name="review_account_request"),
    path("administrator/accounts/<int:user_id>/access/", change_account_access, name="change_account_access"),
    path("administrator/accounts/<int:user_id>/delete/", delete_school_account, name="delete_school_account"),
    path("administrator/enrollment-requests/<int:request_id>/review/", review_enrollment_request, name="review_enrollment_request"),
    path("admin/", admin.site.urls),
]
