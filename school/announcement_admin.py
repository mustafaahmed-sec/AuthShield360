from django.contrib import admin

from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "is_active", "starts_on", "ends_on", "created_at")
    list_filter = ("audience", "is_active", "starts_on", "ends_on")
    search_fields = ("title", "body")
    ordering = ("-created_at", "-pk")
    readonly_fields = ("created_at",)
