from django.contrib import admin
from django.urls import path

from accounts.views import (
    BaselineLoginView,
    BaselineLogoutView,
    password_reset_request,
    password_reset_resend,
    password_reset_verify,
    otp_resend,
    otp_sms_authorize_send,
    otp_sms_mark_sent,
    otp_sms_record_failure,
    otp_verify,
    registration_status,
    signup,
    signup_options,
    password_change,
)
from school.admin_views import (
    admin_management,
    add_student,
    admin_attendance,
    change_account_access,
    delete_school_account,
    reset_school_account_password,
    preview_school_portal,
    review_account_request,
    review_enrollment_request,
)
from school.teacher_views import (
    create_assignment,
    create_exam_result,
    edit_assigned_student,
    request_enrollment_change,
    teacher_attendance,
    teacher_students,
    reset_assigned_student_password,
)
from school.views import dashboard, home


urlpatterns = [
    path("", home, name="home"),
    path("signup/", signup_options, name="signup"),
    path("signup/student/", signup, {"role": "student"}, name="student_signup"),
    path("signup/teacher/", signup, {"role": "teacher"}, name="teacher_signup"),
    path("signup/status/", registration_status, name="registration_status"),
    path("password/change/", password_change, name="password_change"),
    path("password/reset/", password_reset_request, name="password_reset_request"),
    path("password/reset/verify/", password_reset_verify, name="password_reset_verify"),
    path("password/reset/resend/", password_reset_resend, name="password_reset_resend"),
    path("login/", BaselineLoginView.as_view(), name="login"),
    path("login/verify/", otp_verify, name="otp_verify"),
    path("login/verify/resend/", otp_resend, name="otp_resend"),
    path("login/verify/sms/authorize/", otp_sms_authorize_send, name="otp_sms_authorize_send"),
    path("login/verify/sms/sent/", otp_sms_mark_sent, name="otp_sms_mark_sent"),
    path("login/verify/sms/failure/", otp_sms_record_failure, name="otp_sms_record_failure"),
    path("logout/", BaselineLogoutView.as_view(), name="logout"),
    path("dashboard/", dashboard, name="dashboard"),
    path("teacher/assignments/new/", create_assignment, name="create_assignment"),
    path("teacher/results/new/", create_exam_result, name="create_exam_result"),
    path("teacher/students/", teacher_students, name="teacher_students"),
    path("teacher/attendance/", teacher_attendance, name="teacher_attendance"),
    path("teacher/students/<int:student_id>/edit/", edit_assigned_student, name="edit_assigned_student"),
    path("teacher/students/<int:student_id>/reset-password/", reset_assigned_student_password, name="reset_assigned_student_password"),
    path("teacher/enrollment-requests/new/", request_enrollment_change, name="request_enrollment_change"),
    path("administrator/management/", admin_management, name="admin_management"),
    path("administrator/attendance/", admin_attendance, name="admin_attendance"),
    path("administrator/accounts/<int:user_id>/preview/", preview_school_portal, name="preview_school_portal"),
    path("administrator/students/new/", add_student, name="add_student"),
    path("administrator/accounts/<int:user_id>/review/", review_account_request, name="review_account_request"),
    path("administrator/accounts/<int:user_id>/access/", change_account_access, name="change_account_access"),
    path("administrator/accounts/<int:user_id>/delete/", delete_school_account, name="delete_school_account"),
    path("administrator/accounts/<int:user_id>/reset-password/", reset_school_account_password, name="reset_school_account_password"),
    path("administrator/enrollment-requests/<int:request_id>/review/", review_enrollment_request, name="review_enrollment_request"),
    path("admin/", admin.site.urls),
]


