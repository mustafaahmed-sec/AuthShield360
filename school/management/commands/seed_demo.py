"""Create a balanced, repeatable fictional K–12 school roster for the demo."""

import json
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from school.models import Assignment, Course, Enrollment, ExamResult, StudentRecord


STUDENT_TARGET = 486
TEACHER_TARGET = 32
ADMIN_TARGET = 3
ACADEMIC_YEAR = "2026-27"
COURSE_PREFIX = "D26-"
STUDENT_EMAIL = "ali.student@example.test"
TEACHER_EMAIL = "mina.teacher@example.test"
ADMIN_EMAIL = "sara.admin@example.test"

# The three existing demo logins remain the only accounts with demo passwords.
# Other seeded accounts use Django's unusable-password marker until an
# administrator deliberately provisions a real demo credential.
ADMINISTRATORS = (
    (ADMIN_EMAIL, "Sara Miller"),
    ("demo.admin.01@example.test", "Grace Thompson"),
    ("demo.admin.02@example.test", "Amina Qureshi"),
)

# The faculty names are taken from the supplied fictional directory. The
# existing Mina account and one additional fictional teacher bring the total
# to 32. Teachers are grouped by the core subject they teach in this demo.
TEACHER_GROUPS = (
    (
        "ELA",
        "English Language Arts",
        (
            ("demo.teacher.01@example.test", "Sarah Jenkins"),
            ("demo.teacher.02@example.test", "David Miller"),
            ("demo.teacher.03@example.test", "Amanda Higgins"),
            ("demo.teacher.04@example.test", "Jessica Taylor"),
            ("demo.teacher.05@example.test", "Layla Siddiqui"),
            ("demo.teacher.06@example.test", "Catherine Brooks"),
            ("demo.teacher.07@example.test", "Laura Gallagher"),
            ("demo.teacher.31@example.test", "Zainab Farooq"),
        ),
    ),
    (
        "MTH",
        "Mathematics",
        (
            ("demo.teacher.08@example.test", "Robert Vance"),
            ("demo.teacher.09@example.test", "Elizabeth Ross"),
            ("demo.teacher.10@example.test", "Rachel Adams"),
            ("demo.teacher.11@example.test", "Marcus Bennett"),
            ("demo.teacher.12@example.test", "Edward Mitchell"),
            ("demo.teacher.13@example.test", "Nicholas Turner"),
            ("demo.teacher.14@example.test", "Gregory Harrison"),
            ("demo.teacher.15@example.test", "Oliver Brooks"),
        ),
    ),
    (
        "SCI",
        "Science and Computing",
        (
            ("demo.teacher.16@example.test", "Christopher Hayes"),
            ("demo.teacher.17@example.test", "James Patterson"),
            ("demo.teacher.18@example.test", "Thomas Wright"),
            ("demo.teacher.19@example.test", "Daniel Cooper"),
            ("demo.teacher.20@example.test", "Fatima Qureshi"),
            ("demo.teacher.21@example.test", "Victoria Stone"),
            ("demo.teacher.22@example.test", "Bilal Ahmed"),
            ("demo.teacher.23@example.test", "Hamza Malik"),
            (TEACHER_EMAIL, "Mina Rahman"),
        ),
    ),
    (
        "SOC",
        "Social Studies",
        (
            ("demo.teacher.24@example.test", "Rebecca Al-Mansoor"),
            ("demo.teacher.25@example.test", "Tariq Mahmoud"),
            ("demo.teacher.26@example.test", "Yusuf Al-Hassan"),
            ("demo.teacher.27@example.test", "Andrew Coleman"),
            ("demo.teacher.28@example.test", "Maryam Khan"),
            ("demo.teacher.29@example.test", "Stephanie Myers"),
            ("demo.teacher.30@example.test", "Jennifer Morgan"),
        ),
    ),
)

GRADE_NAMES = ("Kindergarten",) + tuple(f"Grade {grade}" for grade in range(1, 13))
def course_title(subject_code, grade_index):
    if subject_code == "ELA":
        return "Early Literacy" if grade_index <= 1 else "English Language Arts"
    if subject_code == "MTH":
        if grade_index <= 5:
            return "Foundations of Mathematics"
        if grade_index <= 8:
            return "Middle School Mathematics"
        return ("Algebra and Functions", "Geometry", "Algebra II", "Pre-Calculus")[min(grade_index - 9, 3)]
    if subject_code == "SCI":
        if grade_index <= 5:
            return "Discovery Science"
        if grade_index <= 8:
            return "General Science"
        return ("Biology", "Chemistry", "Physics", "Computer Science")[min(grade_index - 9, 3)]
    if grade_index <= 5:
        return "Community and Social Studies"
    if grade_index <= 8:
        return "History and Geography"
    return "History and Government"


class Command(BaseCommand):
    help = "Create 486 fictional students, 32 teachers, 3 administrators, and linked academic demo records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Rebuild generated demo accounts and restore the seeded school records; keeps the three primary demo accounts and course history.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if options["reset"]:
            # Preserve courses referenced by roster requests (their FK is
            # protected) and retain historical decisions linked to them.
            User.objects.filter(email__startswith="demo.student.", role=User.Role.STUDENT).delete()
            User.objects.filter(email__startswith="demo.teacher.", role=User.Role.TEACHER).delete()
            User.objects.filter(email__startswith="demo.admin.", role=User.Role.ADMIN).delete()

        self._ensure_primary_account(User, STUDENT_EMAIL, "Ali Khan", User.Role.STUDENT, options["reset"])
        self._ensure_primary_account(User, TEACHER_EMAIL, "Mina Rahman", User.Role.TEACHER, options["reset"])
        self._ensure_primary_account(User, ADMIN_EMAIL, "Sara Miller", User.Role.ADMIN, options["reset"])

        teacher_users = self._ensure_teachers(User)
        self._ensure_administrators(User)
        student_users = self._ensure_students(User)

        course_codes = self._seed_academic_records(student_users, teacher_users, reset_existing=options["reset"])
        seeded_courses = Course.objects.filter(code__in=course_codes)
        seeded_enrollments = Enrollment.objects.filter(student__in=student_users, course__in=seeded_courses)
        seeded_results = ExamResult.objects.filter(student__in=student_users, course__in=seeded_courses)
        self.stdout.write(
            self.style.SUCCESS(
                f"Ready: {len(student_users)} seeded students, "
                f"{sum(len(group) for _, group in teacher_users)} seeded teachers, "
                f"{len(ADMINISTRATORS)} seeded administrators, "
                f"{seeded_courses.count()} courses, "
                f"{Assignment.objects.filter(course__in=seeded_courses).count()} assignments, "
                f"{seeded_enrollments.count()} enrollments, and {seeded_results.count()} exam results."
            )
        )

    def _ensure_primary_account(self, User, email, name, role, reset_existing=False):
        user, created = User.objects.get_or_create(
            email=email,
            defaults={"full_name": name, "role": role},
        )
        if user.role != role:
            raise CommandError(f"The reserved demo account {email} already exists with a different role.")
        if created:
            user.full_name = name
            user.set_unusable_password()
            user.save(update_fields=["full_name", "password"])
        elif reset_existing and user.full_name != name:
            user.full_name = name
            user.save(update_fields=["full_name"])
        if role == User.Role.ADMIN and (not user.is_staff or not user.is_superuser):
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["is_staff", "is_superuser"])

    def _ensure_teachers(self, User):
        specs = [item for _, _, group in TEACHER_GROUPS for item in group]
        existing = {
            user.email: user
            for user in User.objects.filter(email__in=[email for email, _ in specs])
        }
        created = []
        for email, name in specs:
            user = existing.get(email)
            if user and user.role != User.Role.TEACHER:
                raise CommandError(f"Reserved fictional teacher email {email} already has another role.")
            if not user:
                user = User(email=email, full_name=name, role=User.Role.TEACHER)
                user.set_unusable_password()
                created.append(user)
                existing[email] = user
        if created:
            User.objects.bulk_create(created, batch_size=500)

        result = []
        for subject_code, _, group_specs in TEACHER_GROUPS:
            result.append((subject_code, [existing[email] for email, _ in group_specs]))
        if sum(len(group) for _, group in result) != TEACHER_TARGET:
            raise CommandError("The configured teacher roster does not match the 32-teacher target.")
        return result

    def _ensure_administrators(self, User):
        existing = {
            user.email: user
            for user in User.objects.filter(email__in=[email for email, _ in ADMINISTRATORS])
        }
        created = []
        changed = []
        for email, name in ADMINISTRATORS:
            user = existing.get(email)
            if user and user.role != User.Role.ADMIN:
                raise CommandError(f"Reserved fictional administrator email {email} already has another role.")
            if not user:
                user = User(
                    email=email,
                    full_name=name,
                    role=User.Role.ADMIN,
                    is_staff=True,
                    is_superuser=True,
                )
                user.set_unusable_password()
                created.append(user)
                existing[email] = user
            if not user.is_staff or not user.is_superuser:
                user.is_staff = True
                user.is_superuser = True
                changed.append(user)
        if created:
            User.objects.bulk_create(created, batch_size=500)
        if changed:
            User.objects.bulk_update(changed, ["is_staff", "is_superuser"], batch_size=500)

    def _ensure_students(self, User):
        fixture_path = Path(__file__).resolve().parents[2] / "data" / "demo_students.json"
        profiles = json.loads(fixture_path.read_text(encoding="utf-8"))
        if len(profiles) != STUDENT_TARGET - 1:
            raise CommandError("The fictional student-name fixture must contain exactly 485 profiles.")
        expected_emails = [f"demo.student.{number:04d}@example.test" for number in range(1, len(profiles) + 1)]
        existing = {user.email: user for user in User.objects.filter(email__in=expected_emails)}
        created = []
        for number, profile in enumerate(profiles, start=1):
            email = expected_emails[number - 1]
            user = existing.get(email)
            if user and user.role != User.Role.STUDENT:
                raise CommandError(f"Reserved fictional student email {email} already belongs to another role.")
            if user and user.approval_status != User.ApprovalStatus.APPROVED:
                raise CommandError(f"Reserved fictional student email {email} has a pending or rejected request.")
            if user:
                continue
            user = User(email=email, full_name=profile["full_name"], role=User.Role.STUDENT)
            user.set_unusable_password()
            created.append(user)
        if created:
            User.objects.bulk_create(created, batch_size=500)

        roster = {user.email: user for user in User.objects.filter(email__in=[STUDENT_EMAIL, *expected_emails])}
        students = [roster[email] for email in [STUDENT_EMAIL, *expected_emails]]
        if len(students) != STUDENT_TARGET:
            raise CommandError("The reserved fictional student roster is incomplete.")
        return students

    def _seed_academic_records(self, students, teacher_groups, reset_existing=False):
        student_fixture_path = Path(__file__).resolve().parents[2] / "data" / "demo_students.json"
        source_profiles = json.loads(student_fixture_path.read_text(encoding="utf-8"))

        grade_slots = []
        grade_counts = []
        for grade_index, grade in enumerate(GRADE_NAMES):
            grade_count = 38 if grade_index < 5 else 37
            grade_counts.append(grade_count)
            for section, section_count in (("A", (grade_count + 1) // 2), ("B", grade_count // 2)):
                for student_in_section in range(section_count):
                    age = min(5 + grade_index + (1 if (student_in_section + grade_index) % 4 == 0 else 0), 18)
                    grade_slots.append({"grade_index": grade_index, "grade": grade, "section": section, "age": age})

        # Keep the featured Student login as a Grade 10 example while keeping
        # every grade between 37 and 38 students.
        grade_ten_slot = sum(grade_counts[:10])
        grade_slots[0], grade_slots[grade_ten_slot] = grade_slots[grade_ten_slot], grade_slots[0]

        teacher_groups_by_code = dict(teacher_groups)
        subjects = [
            (subject_code, subject_name, teacher_groups_by_code[subject_code])
            for subject_code, subject_name, _ in TEACHER_GROUPS
        ]
        teacher_by_email = {teacher.email: teacher for _, group in teacher_groups for teacher in group}
        course_specs = []
        for grade_index, grade in enumerate(GRADE_NAMES):
            grade_code = "K" if grade_index == 0 else f"G{grade_index}"
            for section in ("A", "B"):
                class_index = grade_index * 2 + (section == "B")
                for subject_index, (subject_code, _, teacher_users) in enumerate(subjects):
                    teacher_index = min(len(teacher_users) - 1, class_index * len(teacher_users) // 26)
                    teacher = teacher_users[teacher_index]
                    is_featured_science = grade_index == 10 and section == "A" and subject_code == "SCI"
                    course_code = "SCI-101" if is_featured_science else f"{COURSE_PREFIX}{grade_code}-{subject_code}-{section}"
                    if is_featured_science:
                        teacher = teacher_by_email[TEACHER_EMAIL]
                    title = "Foundations of Science" if is_featured_science else f"{grade} {section} · {course_title(subject_code, grade_index)}"
                    course_specs.append(
                        ((grade_index, section, subject_index), course_code, title, teacher, is_featured_science)
                    )

        if len(grade_slots) != STUDENT_TARGET:
            raise CommandError("The grade distribution does not add up to 486 students.")

        requested_course_codes = [spec[1] for spec in course_specs]
        existing_courses = {
            course.code: course
            for course in Course.objects.filter(code__in=requested_course_codes)
        }
        courses = {}
        new_courses = []
        changed_courses = []
        existing_course_codes = set(existing_courses)
        for key, code, title, teacher, _ in course_specs:
            course = existing_courses.get(code)
            if course is None:
                course = Course(code=code, title=title, teacher=teacher)
                new_courses.append(course)
                existing_courses[code] = course
            elif reset_existing and (course.title != title or course.teacher_id != teacher.pk):
                course.title = title
                course.teacher = teacher
                changed_courses.append(course)
            courses[key] = course
        if new_courses:
            Course.objects.bulk_create(new_courses, batch_size=500)
        if changed_courses:
            Course.objects.bulk_update(changed_courses, ["title", "teacher"], batch_size=500)

        assignment_specs = []
        for key, code, _, _, is_featured_science in course_specs:
            grade_index, _, subject_index = key
            course = courses[key]
            subject_name = subjects[subject_index][1]
            title = "Observation journal" if is_featured_science else f"Term 1 {subject_name} Check-In"
            description = (
                "Record three observations from a fictional lab exercise."
                if is_featured_science
                else f"Fictional {ACADEMIC_YEAR} learning check for {GRADE_NAMES[grade_index]} students."
            )
            assignment_specs.append((course, title, description, date(2026, 10, 16)))

        existing_assignments = {
            (assignment.course_id, assignment.title): assignment
            for assignment in Assignment.objects.filter(course__in=list(courses.values()))
        }
        new_assignments = []
        changed_assignments = []
        for course, title, description, due_date in assignment_specs:
            assignment = existing_assignments.get((course.pk, title))
            if assignment is None:
                assignment = Assignment(course=course, title=title, description=description, due_date=due_date)
                new_assignments.append(assignment)
            elif reset_existing and (assignment.description != description or assignment.due_date != due_date):
                assignment.description = description
                assignment.due_date = due_date
                changed_assignments.append(assignment)
        if new_assignments:
            Assignment.objects.bulk_create(new_assignments, batch_size=500)
        if changed_assignments:
            Assignment.objects.bulk_update(changed_assignments, ["description", "due_date"], batch_size=500)

        student_ids = [student.pk for student in students]
        existing_records = {
            record.student_id: record
            for record in StudentRecord.objects.filter(student_id__in=student_ids)
        }
        records_by_admission = {
            record.admission_number: record.student_id
            for record in StudentRecord.objects.all()
        }
        student_details = []
        new_records = []
        changed_records = []

        for student_index, (student, slot) in enumerate(zip(students, grade_slots, strict=True)):
            if student.email == STUDENT_EMAIL:
                gender = StudentRecord.Gender.BOY
            elif student.email.startswith("demo.student."):
                roster_number = int(student.email.split(".")[2].split("@")[0])
                profile_index = roster_number - 1
                if profile_index < len(source_profiles):
                    gender = (
                        StudentRecord.Gender.BOY
                        if source_profiles[profile_index]["gender"] == "boy"
                        else StudentRecord.Gender.GIRL
                    )
                else:
                    gender = StudentRecord.Gender.BOY if student_index % 2 else StudentRecord.Gender.GIRL
            else:
                gender = StudentRecord.Gender.NOT_SPECIFIED

            admission_number = f"AS-{student_index + 1:04d}"
            existing_owner = records_by_admission.get(admission_number)
            if existing_owner is not None and existing_owner != student.pk:
                raise CommandError(f"Admission number {admission_number} is already assigned to another student.")
            record = existing_records.get(student.pk)
            if record is None:
                record = StudentRecord(
                    student=student,
                    admission_number=admission_number,
                    grade=slot["grade"],
                    age=slot["age"],
                    gender=gender,
                )
                new_records.append(record)
            else:
                if reset_existing and (
                    record.admission_number != admission_number
                    or record.grade != slot["grade"]
                    or record.age != slot["age"]
                    or record.gender != gender
                ):
                    record.admission_number = admission_number
                    record.grade = slot["grade"]
                    record.age = slot["age"]
                    record.gender = gender
                    changed_records.append(record)
            student_details.append((student, slot))

        if new_records:
            StudentRecord.objects.bulk_create(new_records, batch_size=500)
        if changed_records:
            StudentRecord.objects.bulk_update(
                changed_records,
                ["admission_number", "grade", "age", "gender"],
                batch_size=500,
            )

        course_list = list(courses.values())
        course_ids = [course.pk for course in course_list]
        existing_enrollments = set(
            Enrollment.objects.filter(student_id__in=student_ids, course_id__in=course_ids)
            .values_list("student_id", "course_id")
        )
        new_enrollments = []
        existing_results = {
            (result.student_id, result.course_id, result.exam_name): result
            for result in ExamResult.objects.filter(student_id__in=student_ids, course_id__in=course_ids)
        }
        new_results = []
        changed_results = []

        for student_index, (student, slot) in enumerate(student_details):
            grade_index = slot["grade_index"]
            section = slot["section"]
            for subject_index, (_, subject_name, _) in enumerate(subjects):
                course = courses[(grade_index, section, subject_index)]
                should_fill_relation = (
                    reset_existing
                    or student.pk not in existing_records
                    or course.code not in existing_course_codes
                )
                if should_fill_relation and (student.pk, course.pk) not in existing_enrollments:
                    new_enrollments.append(Enrollment(student=student, course=course))
                score = 65 + ((student_index * 13 + grade_index * 7 + subject_index * 11) % 36)
                exam_name = "Sample term exam" if course.code == "SCI-101" else f"{ACADEMIC_YEAR} Term 1 {subject_name} Check-In"
                result = existing_results.get((student.pk, course.pk, exam_name))
                if result is None and should_fill_relation:
                    new_results.append(ExamResult(student=student, course=course, exam_name=exam_name, score=score, max_score=100))
                elif result is not None and reset_existing and (result.score != score or result.max_score != 100):
                    result.score = score
                    result.max_score = 100
                    changed_results.append(result)

        if new_enrollments:
            Enrollment.objects.bulk_create(new_enrollments, batch_size=500)
        if new_results:
            ExamResult.objects.bulk_create(new_results, batch_size=500)
        if changed_results:
            ExamResult.objects.bulk_update(changed_results, ["score", "max_score"], batch_size=500)
        return requested_course_codes
