# app.py - Complete School ERP System
import os
import secrets
import json
from datetime import datetime, date, timedelta  # ADD timedelta here
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, IntegerField, EmailField, DateField, BooleanField, SubmitField, ValidationError
from wtforms.validators import DataRequired, Email, Length, EqualTo, Optional
from flask_migrate import Migrate
import psycopg2
from psycopg2.extras import RealDictCursor
from sqlalchemy import and_, or_
import logging
from logging.handlers import RotatingFileHandler
import uuid
from datetime import datetime, date, timedelta
from wtforms import StringField, PasswordField, SelectField, IntegerField, EmailField, DateField, BooleanField, SubmitField, ValidationError, FloatField

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:Ac%405121999@localhost/school_erp')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ==================== DATABASE MODELS ====================

def role_required(roles):
    """Decorator to require specific roles"""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                flash('Access denied. Insufficient permissions.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def school_active_required(f):
    """Decorator to require school to be active for non-developer users"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != 'developer' and current_user.school:
            if not current_user.school.is_active:
                flash('This school has been suspended. Please contact the system administrator.', 'danger')
                return redirect(url_for('logout'))
        return f(*args, **kwargs)
    return decorated_function


# ==================== FEE MANAGEMENT MODELS ====================

class FeeStructure(db.Model):
    __tablename__ = 'fee_structures'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    amount = db.Column(db.Float, nullable=False)
    frequency = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=True)
    
    # Enhanced relationships
    school = db.relationship('School', backref='fee_structures')
    session = db.relationship('AcademicSession', backref='fee_structures')
    class_ = db.relationship('Class', backref='fee_structures')
    student_fees = db.relationship('StudentFee', 
                                  back_populates='fee_structure',
                                  cascade='all, delete-orphan')
    
    # Helper method
    def get_applicable_students(self):
        """Get students who should have this fee"""
        if self.class_id:
            # Get students in specific class for this session
            enrollments = StudentEnrollment.query.filter_by(
                class_id=self.class_id,
                session_id=self.session_id,
                is_active=True
            ).all()
            return [enrollment.student for enrollment in enrollments]
        else:
            # Get all active students in the school
            return Student.query.filter_by(
                school_id=self.school_id,
                is_active=True
            ).all()


# ==================== TIMETABLE MODELS ====================

# ==================== ENHANCED TIMETABLE MODELS ====================

class TimetableTemplate(db.Model):
    """Templates for reusing timetable structures"""
    __tablename__ = 'timetable_templates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    
    # Relationships
    school = db.relationship('School', backref='timetable_templates')
    periods = db.relationship('TimetableTemplatePeriod', back_populates='template', cascade='all, delete-orphan')

class TimetableTemplatePeriod(db.Model):
    """Predefined periods for templates"""
    __tablename__ = 'timetable_template_periods'
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Integer, nullable=False)
    period = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    subject_default = db.Column(db.String(100))
    template_id = db.Column(db.Integer, db.ForeignKey('timetable_templates.id'), nullable=False)
    
    template = db.relationship('TimetableTemplate', back_populates='periods')

class TimetableColor(db.Model):
    """Color scheme for subjects/classes"""
    __tablename__ = 'timetable_colors'
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    color_code = db.Column(db.String(7), nullable=False)  # Hex color
    text_color = db.Column(db.String(7), default='#ffffff')
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    
    school = db.relationship('School', backref='timetable_colors')
    
    __table_args__ = (db.UniqueConstraint('school_id', 'subject', name='unique_subject_color'),)

class TeacherAvailability(db.Model):
    """Track teacher availability for timetable planning"""
    __tablename__ = 'teacher_availability'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    day = db.Column(db.Integer, nullable=False)  # 0-6
    period = db.Column(db.Integer, nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    
    teacher = db.relationship('User', foreign_keys=[teacher_id])
    session = db.relationship('AcademicSession', backref='teacher_availability')
    
    __table_args__ = (db.UniqueConstraint('teacher_id', 'day', 'period', 'session_id', name='unique_teacher_availability'),)
# ==================== ATTENDANCE MODELS ====================

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(20), nullable=False)  # 'present', 'absent', 'late', 'half_day'
    check_in_time = db.Column(db.Time, nullable=True)
    check_out_time = db.Column(db.Time, nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign keys
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    marked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relationships
    student = db.relationship('Student', backref='attendance_records')
    class_ = db.relationship('Class', backref='attendance')
    session = db.relationship('AcademicSession', backref='attendance')
    marked_by_user = db.relationship('User', foreign_keys=[marked_by])

class AttendanceSummary(db.Model):
    __tablename__ = 'attendance_summary'
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    total_days = db.Column(db.Integer, default=0)
    present_days = db.Column(db.Integer, default=0)
    absent_days = db.Column(db.Integer, default=0)
    late_days = db.Column(db.Integer, default=0)
    half_days = db.Column(db.Integer, default=0)
    attendance_percentage = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    
    # Relationships
    student = db.relationship('Student', backref='attendance_summaries')
    class_ = db.relationship('Class', backref='attendance_summaries')
    session = db.relationship('AcademicSession', backref='attendance_summaries')

# ==================== ATTENDANCE FORMS ====================

class TakeAttendanceForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()], default=date.today, format='%Y-%m-%d')
    submit = SubmitField('Take Attendance')

class AttendanceRecordForm(FlaskForm):
    """Dynamic form for individual student attendance"""
    student_id = IntegerField('Student ID')
    status = SelectField('Status', choices=[
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('half_day', 'Half Day')
    ], validators=[DataRequired()])
    notes = StringField('Notes')

# ==================== ATTENDANCE UTILITY FUNCTIONS ====================

def get_attendance_stats(class_id, session_id, date_range='month'):
    """Get attendance statistics for a class"""
    today = date.today()
    
    if date_range == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif date_range == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    else:  # year
        start_date = date(today.year, 1, 1)
        end_date = today
    
    # Get all attendance records for the period
    attendance_records = Attendance.query.filter(
        Attendance.class_id == class_id,
        Attendance.session_id == session_id,
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all()
    
    # Get total students in class
    total_students = StudentEnrollment.query.filter_by(
        class_id=class_id,
        session_id=session_id,
        is_active=True
    ).count()
    
    if not attendance_records:
        return {
            'total_days': 0,
            'avg_attendance': 0,
            'present_today': 0,
            'absent_today': 0,
            'attendance_rate': 0,
            'total_students': total_students
        }
    
    # Group by date
    attendance_by_date = {}
    for record in attendance_records:
        if record.date not in attendance_by_date:
            attendance_by_date[record.date] = {'present': 0, 'total': 0}
        attendance_by_date[record.date]['total'] += 1
        if record.status == 'present':
            attendance_by_date[record.date]['present'] += 1
    
    # Calculate statistics
    total_days = len(attendance_by_date)
    total_present = sum([day['present'] for day in attendance_by_date.values()])
    total_records = sum([day['total'] for day in attendance_by_date.values()])
    
    # Today's attendance
    today_records = Attendance.query.filter(
        Attendance.class_id == class_id,
        Attendance.session_id == session_id,
        Attendance.date == today
    ).all()
    
    present_today = len([r for r in today_records if r.status == 'present'])
    absent_today = len([r for r in today_records if r.status == 'absent'])
    
    avg_attendance = (total_present / total_records * 100) if total_records > 0 else 0
    
    return {
        'total_days': total_days,
        'avg_attendance': round(avg_attendance, 1),
        'present_today': present_today,
        'absent_today': absent_today,
        'attendance_rate': avg_attendance,
        'total_students': total_students
    }

def get_student_attendance_stats(student_id, session_id):
    """Get attendance statistics for a specific student"""
    today = date.today()
    current_month = today.month
    current_year = today.year
    
    # Get attendance for current month
    attendance_records = Attendance.query.filter(
        Attendance.student_id == student_id,
        Attendance.session_id == session_id,
        db.extract('month', Attendance.date) == current_month,
        db.extract('year', Attendance.date) == current_year
    ).all()
    
    total_days = len(attendance_records)
    present_days = len([r for r in attendance_records if r.status == 'present'])
    absent_days = len([r for r in attendance_records if r.status == 'absent'])
    late_days = len([r for r in attendance_records if r.status == 'late'])
    half_days = len([r for r in attendance_records if r.status == 'half_day'])
    
    attendance_percentage = (present_days / total_days * 100) if total_days > 0 else 0
    
    return {
        'total_days': total_days,
        'present_days': present_days,
        'absent_days': absent_days,
        'late_days': late_days,
        'half_days': half_days,
        'attendance_percentage': round(attendance_percentage, 1),
        'current_month': today.strftime('%B %Y')
    }

def get_attendance_trends(class_id, session_id, days=30):
    """Get attendance trends for the last N days"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days-1)
    
    trends = []
    
    # Get all attendance records for the period
    attendance_records = Attendance.query.filter(
        Attendance.class_id == class_id,
        Attendance.session_id == session_id,
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all()
    
    # Group by date
    attendance_by_date = {}
    for record in attendance_records:
        if record.date not in attendance_by_date:
            attendance_by_date[record.date] = {'present': 0, 'total': 0}
        attendance_by_date[record.date]['total'] += 1
        if record.status == 'present':
            attendance_by_date[record.date]['present'] += 1
    
    # Fill in all dates
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        if current_date in attendance_by_date:
            day_data = attendance_by_date[current_date]
            attendance_rate = (day_data['present'] / day_data['total'] * 100) if day_data['total'] > 0 else 0
            trends.append({
                'date': date_str,
                'day': current_date.strftime('%a'),
                'present': day_data['present'],
                'total': day_data['total'],
                'rate': round(attendance_rate, 1),
                'has_data': True
            })
        else:
            trends.append({
                'date': date_str,
                'day': current_date.strftime('%a'),
                'present': 0,
                'total': 0,
                'rate': 0,
                'has_data': False
            })
        current_date += timedelta(days=1)
    
    return trends

# ==================== ATTENDANCE ROUTES ====================

@app.route('/teacher/attendance')
@role_required(['teacher'])
@school_active_required
def teacher_attendance_dashboard():
    """Teacher attendance dashboard"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get teacher's assignments for current session
    assignments = TeacherAssignment.query.filter_by(
        teacher_id=current_user.id,
        session_id=context['current_session'].id
    ).all()
    
    # Get attendance statistics for each class
    class_stats = []
    today = date.today()
    
    for assignment in assignments:
        class_obj = Class.query.get(assignment.class_id)
        if class_obj:
            stats = get_attendance_stats(class_obj.id, context['current_session'].id, 'month')
            
            # Get today's attendance
            today_attendance = Attendance.query.filter(
                Attendance.class_id == class_obj.id,
                Attendance.session_id == context['current_session'].id,
                Attendance.date == today
            ).all()
            
            attendance_taken = len(today_attendance) > 0
            
            class_stats.append({
                'class': class_obj,
                'assignment': assignment,
                'stats': stats,
                'attendance_taken': attendance_taken,
                'total_students': stats['total_students']
            })
    
    # Get recent attendance activities
    recent_activities = []
    for assignment in assignments[:3]:  # Only get first 3 assignments
        class_obj = Class.query.get(assignment.class_id)
        if class_obj:
            recent_attendance = Attendance.query.filter_by(
                class_id=class_obj.id,
                session_id=context['current_session'].id
            ).order_by(Attendance.date.desc()).limit(3).all()
            
            for att in recent_attendance:
                recent_activities.append({
                    'date': att.date.strftime('%b %d'),
                    'class': class_obj.name,
                    'subject': assignment.subject,
                    'status': f"Attendance taken for {att.date.strftime('%b %d')}",
                    'icon': 'calendar-check',
                    'color': 'primary'
                })
    
    return render_template('teacher_attendance_dashboard.html',
                         context=context,
                         class_stats=class_stats,
                         recent_activities=recent_activities,
                         today=today)

@app.route('/teacher/attendance/take/<int:class_id>', methods=['GET', 'POST'])
@role_required(['teacher'])
@school_active_required
def take_attendance(class_id):
    """Take attendance for a class"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Verify teacher has access to this class
    assignment = TeacherAssignment.query.filter_by(
        teacher_id=current_user.id,
        class_id=class_id,
        session_id=context['current_session'].id
    ).first_or_404()
    
    class_obj = Class.query.get_or_404(class_id)
    form = TakeAttendanceForm()
    
    # Get students in this class
    enrollments = StudentEnrollment.query.filter_by(
        class_id=class_id,
        session_id=context['current_session'].id,
        is_active=True
    ).order_by(StudentEnrollment.roll_number).all()
    
    if not enrollments:
        flash('No students enrolled in this class', 'warning')
        return redirect(url_for('teacher_attendance_dashboard'))
    
    if form.validate_on_submit():
        try:
            attendance_date = form.date.data
            today_attendance = date.today()
            
            # Check if attendance already taken for this date
            existing_attendance = Attendance.query.filter_by(
                class_id=class_id,
                session_id=context['current_session'].id,
                date=attendance_date
            ).first()
            
            if existing_attendance and attendance_date == today_attendance:
                # Update existing attendance
                for enrollment in enrollments:
                    status_key = f"status_{enrollment.student_id}"
                    if status_key in request.form:
                        attendance = Attendance.query.filter_by(
                            student_id=enrollment.student_id,
                            class_id=class_id,
                            session_id=context['current_session'].id,
                            date=attendance_date
                        ).first()
                        
                        if attendance:
                            attendance.status = request.form[status_key]
                            attendance.notes = request.form.get(f"notes_{enrollment.student_id}", '')
                            attendance.updated_at = datetime.utcnow()
                        else:
                            attendance = Attendance(
                                student_id=enrollment.student_id,
                                class_id=class_id,
                                session_id=context['current_session'].id,
                                date=attendance_date,
                                status=request.form[status_key],
                                notes=request.form.get(f"notes_{enrollment.student_id}", ''),
                                marked_by=current_user.id
                            )
                            db.session.add(attendance)
            else:
                # Create new attendance records
                for enrollment in enrollments:
                    status_key = f"status_{enrollment.student_id}"
                    if status_key in request.form:
                        attendance = Attendance(
                            student_id=enrollment.student_id,
                            class_id=class_id,
                            session_id=context['current_session'].id,
                            date=attendance_date,
                            status=request.form[status_key],
                            notes=request.form.get(f"notes_{enrollment.student_id}", ''),
                            marked_by=current_user.id
                        )
                        db.session.add(attendance)
            
            db.session.commit()
            
            # Update attendance summary
            update_attendance_summary(class_id, context['current_session'].id, attendance_date.month, attendance_date.year)
            
            flash(f'Attendance for {attendance_date.strftime("%B %d, %Y")} saved successfully!', 'success')
            return redirect(url_for('view_class_attendance', class_id=class_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving attendance: {str(e)}', 'danger')
    
    # GET request - show attendance form
    # Get existing attendance for today if exists
    attendance_date = form.date.data or date.today()
    existing_attendance = {}
    
    if request.method == 'GET':
        attendance_records = Attendance.query.filter(
            Attendance.class_id == class_id,
            Attendance.session_id == context['current_session'].id,
            Attendance.date == attendance_date
        ).all()
        
        for record in attendance_records:
            existing_attendance[record.student_id] = {
                'status': record.status,
                'notes': record.notes
            }
    
    return render_template('teacher_take_attendance.html',
                         context=context,
                         class_obj=class_obj,
                         assignment=assignment,
                         enrollments=enrollments,
                         form=form,
                         existing_attendance=existing_attendance,
                         attendance_date=attendance_date)

@app.route('/student/profile')
@login_required
def student_profile():
    if current_user.role != 'student':
        abort(403)

    student = current_user.student
    if not student:
        flash('Student record not found.', 'danger')
        return redirect(url_for('dashboard'))

    # Get the current active session for the student's school
    current_session = get_current_session(student.school_id)

    # Get the student's enrollment in that session (if any)
    enrollment = None
    if current_session:
        enrollment = StudentEnrollment.query.filter_by(
            student_id=student.id,
            session_id=current_session.id,
            is_active=True
        ).first()

    return render_template(
        'student_profile.html',
        student=student,
        enrollment=enrollment,
        current_session=current_session,
        context={'school': current_user.school, 'current_session': current_session}
    )

@app.route('/debug-routes')
def debug_routes():
    import urllib
    output = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(rule.methods)
        line = urllib.parse.unquote(f"{rule.endpoint}: {rule.rule} [{methods}]")
        output.append(line)
    return '<br>'.join(sorted(output))

@app.route('/teacher/attendance/view/<int:class_id>')
@role_required(['teacher'])
@school_active_required
def view_class_attendance(class_id):
    """View attendance for a class"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Verify teacher has access to this class
    assignment = TeacherAssignment.query.filter_by(
        teacher_id=current_user.id,
        class_id=class_id,
        session_id=context['current_session'].id
    ).first_or_404()
    
    class_obj = Class.query.get_or_404(class_id)
    
    # Get date range from request
    start_date_str = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date_str = request.args.get('end_date', date.today().isoformat())
    student_id = request.args.get('student_id', '')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = date.today()
    
    # Get students in this class
    enrollments = StudentEnrollment.query.filter_by(
        class_id=class_id,
        session_id=context['current_session'].id,
        is_active=True
    ).order_by(StudentEnrollment.roll_number).all()
    
    # Get attendance records for the date range
    attendance_query = Attendance.query.filter(
        Attendance.class_id == class_id,
        Attendance.session_id == context['current_session'].id,
        Attendance.date >= start_date,
        Attendance.date <= end_date
    )
    
    if student_id:
        attendance_query = attendance_query.filter(Attendance.student_id == student_id)
    
    attendance_records = attendance_query.order_by(Attendance.date.desc()).all()
    
    # Group attendance by student
    attendance_by_student = {}
    for record in attendance_records:
        if record.student_id not in attendance_by_student:
            attendance_by_student[record.student_id] = []
        attendance_by_student[record.student_id].append(record)
    
    # Calculate statistics
    stats = get_attendance_stats(class_id, context['current_session'].id, 'month')
    
    # Get attendance trends
    trends = get_attendance_trends(class_id, context['current_session'].id, 7)
    
    return render_template('teacher_view_attendance.html',
                         context=context,
                         class_obj=class_obj,
                         assignment=assignment,
                         enrollments=enrollments,
                         attendance_records=attendance_records,
                         attendance_by_student=attendance_by_student,
                         stats=stats,
                         trends=trends,
                         start_date=start_date,
                         end_date=end_date,
                         student_id=student_id)

@app.route('/student/attendance')
@login_required
@role_required(['student'])
def student_attendance():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))

    # Get student object
    student = Student.query.filter_by(id=current_user.student_id).first()
    if not student:
        flash('Student record not found', 'danger')
        return redirect(url_for('logout'))

    # Get current academic session
    current_session = get_current_session(student.school_id)
    if not current_session:
        flash('No active session found', 'warning')
        return render_template('student_attendance.html',
                               student=student,
                               attendance_stats={},
                               attendance_records=[],
                               current_session=None,
                               months=[],
                               percentages=[],
                               class_avg=0,
                               subject_attendance={},
                               date=date.today())

    # Get current enrollment
    enrollment = StudentEnrollment.query.filter_by(
        student_id=student.id,
        session_id=current_session.id,
        is_active=True
    ).first()
    if not enrollment:
        flash('You are not enrolled in any class for the current session.', 'warning')
        return redirect(url_for('student_dashboard'))

    # Date range from request (default to current month)
    start_date_str = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date_str = request.args.get('end_date', date.today().isoformat())
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = date.today()

    # Fetch attendance records
    attendance_records = Attendance.query.filter(
        Attendance.student_id == student.id,
        Attendance.session_id == current_session.id,
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).order_by(Attendance.date.desc()).all()

    # Current month stats (using your existing helper)
    attendance_stats = get_student_attendance_stats(student.id, current_session.id)

    # ----- Last 6 months summary for trend chart -----
    six_months_ago = date.today() - timedelta(days=180)
    summaries = AttendanceSummary.query.filter(
        AttendanceSummary.student_id == student.id,
        AttendanceSummary.session_id == current_session.id,
        # Only include summaries from the last 6 months (by month and year)
        db.or_(
            db.and_(AttendanceSummary.year == six_months_ago.year,
                    AttendanceSummary.month >= six_months_ago.month),
            db.and_(AttendanceSummary.year > six_months_ago.year,
                    AttendanceSummary.year <= date.today().year)
        )
    ).order_by(AttendanceSummary.year, AttendanceSummary.month).all()

    months = [f"{s.month:02d}/{s.year}" for s in summaries]   # e.g. "03/2025"
    percentages = [s.attendance_percentage for s in summaries]

    # ----- Class average attendance -----
    class_avg = db.session.query(db.func.avg(AttendanceSummary.attendance_percentage))\
                .filter(AttendanceSummary.class_id == enrollment.class_id,
                        AttendanceSummary.session_id == current_session.id).scalar() or 0

    # ----- Subject-wise attendance (if you track subjects) -----
    # This requires a relationship between Attendance and TeacherAssignment/subject.
    # Below is a sample implementation – adjust to your schema.
    subject_attendance = {}
    # Get all teacher assignments for this class and session
    assignments = TeacherAssignment.query.filter_by(
        class_id=enrollment.class_id,
        session_id=current_session.id
    ).all()

    for assignment in assignments:
        # Count attendance for this student in the class of that subject
        # If you have a subject field in Attendance, join accordingly.
        # Here we assume attendance is per class, not per subject, so we use the same class records.
        # For a more accurate subject-wise, you'd need attendance per subject.
        present = Attendance.query.filter_by(
            student_id=student.id,
            class_id=enrollment.class_id,
            session_id=current_session.id,
            status='present'
        ).count()
        total = Attendance.query.filter_by(
            student_id=student.id,
            class_id=enrollment.class_id,
            session_id=current_session.id
        ).count()
        if total > 0:
            subject_attendance[assignment.subject] = {
                'present': present,
                'total': total,
                'percentage': (present / total) * 100
            }

    return render_template('student_attendance.html',
                           student=student,
                           enrollment=enrollment,
                           attendance_stats=attendance_stats,
                           attendance_records=attendance_records,
                           current_session=current_session,
                           start_date=start_date,
                           end_date=end_date,
                           months=months,
                           percentages=percentages,
                           class_avg=class_avg,
                           subject_attendance=subject_attendance,
                           date=date.today())

def update_attendance_summary(class_id, session_id, month, year):
    """Update attendance summary for a class"""
    # Get all students in the class
    enrollments = StudentEnrollment.query.filter_by(
        class_id=class_id,
        session_id=session_id,
        is_active=True
    ).all()
    
    for enrollment in enrollments:
        # Get attendance records for the month
        attendance_records = Attendance.query.filter(
            Attendance.student_id == enrollment.student_id,
            Attendance.class_id == class_id,
            Attendance.session_id == session_id,
            db.extract('month', Attendance.date) == month,
            db.extract('year', Attendance.date) == year
        ).all()
        
        total_days = len(attendance_records)
        present_days = len([r for r in attendance_records if r.status == 'present'])
        absent_days = len([r for r in attendance_records if r.status == 'absent'])
        late_days = len([r for r in attendance_records if r.status == 'late'])
        half_days = len([r for r in attendance_records if r.status == 'half_day'])
        
        attendance_percentage = (present_days / total_days * 100) if total_days > 0 else 0
        
        # Update or create summary
        summary = AttendanceSummary.query.filter_by(
            student_id=enrollment.student_id,
            class_id=class_id,
            session_id=session_id,
            month=month,
            year=year
        ).first()
        
        if summary:
            summary.total_days = total_days
            summary.present_days = present_days
            summary.absent_days = absent_days
            summary.late_days = late_days
            summary.half_days = half_days
            summary.attendance_percentage = attendance_percentage
        else:
            summary = AttendanceSummary(
                student_id=enrollment.student_id,
                class_id=class_id,
                session_id=session_id,
                month=month,
                year=year,
                total_days=total_days,
                present_days=present_days,
                absent_days=absent_days,
                late_days=late_days,
                half_days=half_days,
                attendance_percentage=attendance_percentage
            )
            db.session.add(summary)
    
    db.session.commit()

# ==================== UTILITY FUNCTIONS ====================

def get_today_attendance(class_id):
    """Check if attendance is taken for today"""
    from datetime import date
    
    attendance = Attendance.query.filter_by(
        class_id=class_id,
        date=date.today()
    ).first()
    
    return attendance is not None

# Update the utility_processor to include this function
@app.context_processor
def utility_processor():
    """Make utility functions available to templates"""
    def get_overdue_fees_count(school_id):
        """Get count of overdue fees for a school"""
        try:
            from datetime import date
            
            current_session = AcademicSession.query.filter_by(
                school_id=school_id, 
                is_current=True
            ).first()
            
            if not current_session:
                return 0
                
            count = db.session.query(StudentFee).join(Student).filter(
                Student.school_id == school_id,
                StudentFee.session_id == current_session.id,
                StudentFee.due_date < date.today(),
                StudentFee.status.in_(['pending', 'partial'])
            ).count()
            
            return count
        except Exception as e:
            print(f"Error in get_overdue_fees_count: {e}")
            return 0
    
    def get_overdue_fees(school_id, limit=5):
        """Get overdue fees for a school"""
        try:
            from datetime import date
            
            current_session = AcademicSession.query.filter_by(
                school_id=school_id, 
                is_current=True
            ).first()
            
            if not current_session:
                return []
                
            overdue_fees = StudentFee.query.join(Student).filter(
                Student.school_id == school_id,
                StudentFee.session_id == current_session.id,
                StudentFee.due_date < date.today(),
                StudentFee.status.in_(['pending', 'partial'])
            ).order_by(StudentFee.due_date).limit(limit).all()
            
            return overdue_fees
        except Exception as e:
            print(f"Error in get_overdue_fees: {e}")
            return []
    
    def get_student_overdue_fees(student_id):
        """Get overdue fee count for a specific student"""
        try:
            from datetime import date
            
            student = Student.query.get(student_id)
            if not student:
                return 0
                
            current_session = AcademicSession.query.filter_by(
                school_id=student.school_id, 
                is_current=True
            ).first()
            
            if not current_session:
                return 0
                
            count = StudentFee.query.filter_by(
                student_id=student_id,
                session_id=current_session.id
            ).filter(
                StudentFee.due_date < date.today(),
                StudentFee.status.in_(['pending', 'partial'])
            ).count()
            
            return count
        except Exception as e:
            print(f"Error in get_student_overdue_fees: {e}")
            return 0
    
    def get_monthly_collection(school_id, session_id):
        """Get monthly collection data for charts"""
        try:
            from datetime import datetime
            import calendar
            
            session = AcademicSession.query.get(session_id)
            if not session:
                return []
            
            year = session.start_date.year
            monthly_data = []
            
            for month in range(1, 13):
                month_start = datetime(year, month, 1)
                if month == 12:
                    month_end = datetime(year + 1, 1, 1)
                else:
                    month_end = datetime(year, month + 1, 1)
                
                total = db.session.query(db.func.coalesce(db.func.sum(FeeTransaction.amount), 0)).join(
                    Student
                ).filter(
                    Student.school_id == school_id,
                    FeeTransaction.transaction_date >= month_start,
                    FeeTransaction.transaction_date < month_end,
                    FeeTransaction.transaction_type == 'payment',
                    FeeTransaction.status == 'success'
                ).scalar()
                
                monthly_data.append({
                    'month': calendar.month_abbr[month],
                    'amount': float(total or 0)
                })
            
            return monthly_data
        except Exception as e:
            print(f"Error in get_monthly_collection: {e}")
            return [{'month': m, 'amount': 0} for m in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                                                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']]
    
    # ADD THE get_today_attendance FUNCTION HERE
    def get_today_attendance_helper(class_id):
        """Helper function for templates to check today's attendance"""
        try:
            from datetime import date
            
            # Check if attendance exists for today
            attendance = Attendance.query.filter_by(
                class_id=class_id,
                date=date.today()
            ).first()
            
            return attendance is not None
        except Exception as e:
            print(f"Error in get_today_attendance_helper: {e}")
            return False
    
    return {
        'get_overdue_fees_count': get_overdue_fees_count,
        'get_overdue_fees': get_overdue_fees,
        'get_student_overdue_fees': get_student_overdue_fees,
        'get_monthly_collection': get_monthly_collection,
        'get_today_attendance': get_today_attendance_helper,  # ADD THIS LINE
        'date': date  # Add date module for templates
    }

class StudentFee(db.Model):
    __tablename__ = 'student_fees'
    id = db.Column(db.Integer, primary_key=True)
    fee_amount = db.Column(db.Float, nullable=False)
    discount_amount = db.Column(db.Float, default=0.0)
    fine_amount = db.Column(db.Float, default=0.0)
    paid_amount = db.Column(db.Float, default=0.0)
    due_date = db.Column(db.Date, nullable=False)
    payment_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='pending')
    payment_method = db.Column(db.String(50))
    transaction_id = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign keys
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    fee_structure_id = db.Column(db.Integer, db.ForeignKey('fee_structures.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=True)
    
    # Enhanced relationships
    student = db.relationship('Student', back_populates='fee_payments')
    fee_structure = db.relationship('FeeStructure', back_populates='student_fees')
    session = db.relationship('AcademicSession', backref='student_fees')
    class_ = db.relationship('Class', backref='fee_records')
    
    # Property for balance
    @property
    def balance(self):
        return self.net_amount - self.paid_amount
    
    @property
    def net_amount(self):
        return self.fee_amount - self.discount_amount + self.fine_amount
    
    @property
    def is_overdue(self):
        return self.due_date < date.today() and self.balance > 0
    
    # Update status automatically
    def update_status(self):
        if self.paid_amount >= self.net_amount:
            self.status = 'paid'
        elif self.paid_amount > 0:
            self.status = 'partial'
        elif self.is_overdue:
            self.status = 'overdue'
        else:
            self.status = 'pending'

def get_school_fee_statistics(school_id, session_id):
    """Get comprehensive fee statistics for a school"""
    try:
        # Get all student fees for the session
        student_fees = StudentFee.query.join(Student).filter(
            Student.school_id == school_id,
            StudentFee.session_id == session_id
        ).all()
        
        # Get all students
        all_students = Student.query.filter_by(
            school_id=school_id,
            is_active=True
        ).all()
        
        # Get all fee structures
        fee_structures = FeeStructure.query.filter_by(
            school_id=school_id,
            session_id=session_id,
            is_active=True
        ).all()
        
        # Calculate which students have fees assigned
        students_with_fees = set([f.student_id for f in student_fees])
        
        return {
            'total_fees': sum(f.fee_amount for f in student_fees),
            'total_paid': sum(f.paid_amount for f in student_fees),
            'total_due': sum(f.net_amount - f.paid_amount for f in student_fees),
            'total_discount': sum(f.discount_amount for f in student_fees),
            'total_fine': sum(f.fine_amount for f in student_fees),
            'total_net': sum(f.net_amount for f in student_fees),
            'paid_count': len([f for f in student_fees if f.status == 'paid']),
            'pending_count': len([f for f in student_fees if f.status == 'pending']),
            'partial_count': len([f for f in student_fees if f.status == 'partial']),
            'overdue_count': len([f for f in student_fees if f.due_date < date.today() and f.balance > 0]),
            'student_fees_count': len(student_fees),
            'total_students': len(all_students),
            'students_without_fees': len(all_students) - len(students_with_fees),
            'fee_structures_count': len(fee_structures),
            'has_unassigned_fees': len(fee_structures) > 0 and len(students_with_fees) == 0
        }
    except Exception as e:
        print(f"Error in get_school_fee_statistics: {e}")
        return {
            'total_fees': 0,
            'total_paid': 0,
            'total_due': 0,
            'total_discount': 0,
            'total_fine': 0,
            'total_net': 0,
            'paid_count': 0,
            'pending_count': 0,
            'partial_count': 0,
            'overdue_count': 0,
            'student_fees_count': 0,
            'total_students': 0,
            'students_without_fees': 0,
            'fee_structures_count': 0,
            'has_unassigned_fees': False
        }
    

@app.route('/admin/debug/classes')
@role_required(['admin'])
def debug_classes():
    """Debug endpoint to check all classes"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    school_id = current_user.school_id
    
    # Get all sessions and their classes
    all_sessions = AcademicSession.query.filter_by(
        school_id=school_id,
        is_active=True
    ).all()
    
    sessions_data = []
    for session in all_sessions:
        classes = Class.query.filter_by(
            school_id=school_id,
            session_id=session.id,
            is_active=True
        ).all()
        
        sessions_data.append({
            'session': session,
            'classes': classes,
            'classes_count': len(classes)
        })
    
    return render_template('admin_debug_classes.html',
                         context=context,
                         sessions_data=sessions_data)

@app.route('/admin/debug/fee-data')
@role_required(['admin'])
def debug_fee_data():
    """Debug endpoint to check fee data"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    school_id = current_user.school_id
    view_session = context.get('view_session') or context['current_session']
    
    # Get all fee structures
    fee_structures = FeeStructure.query.filter_by(
        school_id=school_id,
        session_id=view_session.id
    ).all()
    
    # Get all student fees
    student_fees = StudentFee.query.join(Student).filter(
        Student.school_id==school_id,
        StudentFee.session_id==view_session.id
    ).all()
    
    # Get all students
    students = Student.query.filter_by(
        school_id=school_id,
        is_active=True
    ).all()
    
    # Check if fees are assigned
    fee_assignment_status = []
    for student in students[:5]:  # Check first 5 students
        fees = StudentFee.query.filter_by(
            student_id=student.id,
            session_id=view_session.id
        ).all()
        fee_assignment_status.append({
            'student': f"{student.first_name} {student.last_name}",
            'fee_count': len(fees),
            'fees': [f.fee_structure.name for f in fees]
        })
    
    return render_template('admin_debug_fee_data.html',
                         context=context,
                         fee_structures=fee_structures,
                         fee_structures_count=len(fee_structures),
                         student_fees_count=len(student_fees),
                         students_count=len(students),
                         fee_assignment_status=fee_assignment_status,
                         view_session=view_session)

def assign_fee_to_all_students(fee_structure_id, due_date):
    """Assign fee structure to all applicable students"""
    fee_structure = FeeStructure.query.get(fee_structure_id)
    if not fee_structure:
        return 0
    
    students = fee_structure.get_applicable_students()
    assigned_count = 0
    
    for student in students:
        # Check if fee already exists
        existing = StudentFee.query.filter_by(
            student_id=student.id,
            fee_structure_id=fee_structure.id,
            session_id=fee_structure.session_id
        ).first()
        
        if not existing:
            # Create student fee record
            student_fee = StudentFee(
                student_id=student.id,
                fee_structure_id=fee_structure.id,
                session_id=fee_structure.session_id,
                class_id=student.current_class.id if student.current_class else None,
                fee_amount=fee_structure.amount,
                due_date=due_date,
                status='pending'
            )
            
            # Apply any active discounts
            discounts = FeeDiscount.query.filter(
                FeeDiscount.student_id == student.id,
                FeeDiscount.fee_structure_id == fee_structure.id,
                FeeDiscount.is_active == True,
                FeeDiscount.valid_from <= due_date,
                FeeDiscount.valid_to >= due_date
            ).all()
            
            for discount in discounts:
                if discount.discount_type == 'percentage':
                    student_fee.discount_amount += fee_structure.amount * (discount.value / 100)
                else:
                    student_fee.discount_amount += discount.value
            
            student_fee.update_status()
            db.session.add(student_fee)
            assigned_count += 1
    
    db.session.commit()
    return assigned_count

class FeeTransaction(db.Model):
    __tablename__ = 'fee_transactions'
    id = db.Column(db.Integer, primary_key=True)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'payment', 'discount', 'fine', 'refund'
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50))
    transaction_id = db.Column(db.String(100), unique=True)
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='success')  # 'success', 'failed', 'pending'
    gateway_response = db.Column(db.Text)
    receipt_number = db.Column(db.String(50))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Foreign keys
    student_fee_id = db.Column(db.Integer, db.ForeignKey('student_fees.id'))
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    
    # FIXED: Update relationships
    student_fee = db.relationship('StudentFee', backref='transactions')
    student = db.relationship('Student', back_populates='transactions')
    created_by_user = db.relationship('User', foreign_keys=[created_by])

class FeeDiscount(db.Model):
    __tablename__ = 'fee_discounts'
    id = db.Column(db.Integer, primary_key=True)
    discount_type = db.Column(db.String(50), nullable=False)  # 'percentage', 'fixed'
    value = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(200))
    valid_from = db.Column(db.Date, nullable=False)
    valid_to = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    fee_structure_id = db.Column(db.Integer, db.ForeignKey('fee_structures.id'))
    applied_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # FIXED: Update relationships
    student = db.relationship('Student', back_populates='discounts')
    fee_structure = db.relationship('FeeStructure', backref='discounts')
    applied_by_user = db.relationship('User', foreign_keys=[applied_by])

class DeveloperResetPasswordForm(FlaskForm):
    reason = StringField('Reason for Reset')
    force_logout = BooleanField('Force logout from all sessions', default=True)
    notify_user = BooleanField('Notify user via email', default=True)
    submit = SubmitField('Reset Password')


# ==================== FEE MANAGEMENT FORMS ====================

class CreateFeeStructureForm(FlaskForm):
    name = StringField('Fee Name', validators=[DataRequired()])
    description = StringField('Description')
    amount = FloatField('Amount', validators=[DataRequired()])
    frequency = SelectField('Frequency', choices=[
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('half-yearly', 'Half Yearly'),
        ('yearly', 'Yearly'),
        ('one-time', 'One Time')
    ], validators=[DataRequired()])
    class_id = SelectField('Class (Optional)', coerce=int, validators=[Optional()])
    submit = SubmitField('Create Fee Structure')

class AssignFeeToStudentsForm(FlaskForm):
    fee_structure_id = SelectField('Fee Structure', coerce=int, validators=[DataRequired()])
    due_date = DateField('Due Date', validators=[DataRequired()], format='%Y-%m-%d')
    submit = SubmitField('Assign Fee')

class RecordPaymentForm(FlaskForm):
    amount = FloatField('Payment Amount', validators=[DataRequired()])
    payment_method = SelectField('Payment Method', choices=[
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('bank_transfer', 'Bank Transfer'),
        ('online', 'Online Payment'),
        ('card', 'Debit/Credit Card')
    ], validators=[DataRequired()])
    transaction_id = StringField('Transaction ID (Optional)')
    payment_date = DateField('Payment Date', default=date.today, format='%Y-%m-%d')
    notes = StringField('Notes (Optional)')
    submit = SubmitField('Record Payment')

class ApplyDiscountForm(FlaskForm):
    student_id = SelectField('Student', coerce=int, validators=[DataRequired()])
    discount_type = SelectField('Discount Type', choices=[
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount')
    ], validators=[DataRequired()])
    value = FloatField('Value', validators=[DataRequired()])
    reason = StringField('Reason', validators=[DataRequired()])
    valid_from = DateField('Valid From', default=date.today, format='%Y-%m-%d')
    valid_to = DateField('Valid To', validators=[DataRequired()], format='%Y-%m-%d')
    submit = SubmitField('Apply Discount')

# ==================== FEE MANAGEMENT ROUTES ====================

@app.route('/admin/fee-structures')
@role_required(['admin'])
@school_active_required
def manage_fee_structures():
    """View all fee structures"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_session_context()  # Use the new function
    
    if not context.get('view_session'):
        flash('No active session found', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Get all fee structures for current school and session
    fee_structures = FeeStructure.query.filter_by(
        school_id=current_user.school_id,
        session_id=context['view_session'].id,
        is_active=True
    ).all()
    
    return render_template('admin_fee_structures.html',
                         fee_structures=fee_structures,
                         context=context)

@app.route('/admin/fees/check-data')
@role_required(['admin'])
def check_fee_data():
    """Check and fix fee data issues"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_session_context()
    school_id = current_user.school_id
    session_id = context['view_session'].id
    
    issues = []
    fixes = []
    
    # Check 1: Fee structures without class assignments
    fee_structures = FeeStructure.query.filter_by(
        school_id=school_id,
        session_id=session_id,
        is_active=True
    ).all()
    
    for fs in fee_structures:
        # Count students who should have this fee
        applicable_students = fs.get_applicable_students()
        assigned_fees = StudentFee.query.filter_by(
            fee_structure_id=fs.id,
            session_id=session_id
        ).count()
        
        if applicable_students and assigned_fees == 0:
            issues.append(f"Fee structure '{fs.name}' is not assigned to any students")
            fixes.append({
                'type': 'assign_fees',
                'fee_structure_id': fs.id,
                'name': fs.name,
                'applicable_students': len(applicable_students)
            })
    
    # Check 2: Students without fees
    all_students = Student.query.filter_by(
        school_id=school_id,
        is_active=True
    ).count()
    
    students_with_fees = db.session.query(StudentFee.student_id).filter(
        StudentFee.session_id == session_id
    ).distinct().count()
    
    if students_with_fees < all_students:
        issues.append(f"{all_students - students_with_fees} students have no fees assigned")
    
    return render_template('admin_check_fee_data.html',
                         context=context,
                         issues=issues,
                         fixes=fixes,
                         all_students=all_students,
                         students_with_fees=students_with_fees)

@app.route('/admin/fee-structures/create', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def create_fee_structure():
    """Create a new fee structure"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = CreateFeeStructureForm()
    context = get_school_context()
    
    # Use view_session instead of current_session for consistency
    view_session = context.get('view_session') or context.get('current_session')
    
    if not view_session:
        flash('No active session found', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Populate class choices
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=view_session.id,  # Use view_session.id
        is_active=True
    ).all()
    
    form.class_id.choices = [(0, 'All Classes')] + [(c.id, f"{c.name} ({c.code})") for c in classes]
    
    if form.validate_on_submit():
        try:
            # Create fee structure with view_session
            fee_structure = FeeStructure(
                name=form.name.data,
                description=form.description.data,
                amount=form.amount.data,
                frequency=form.frequency.data,
                school_id=current_user.school_id,
                session_id=view_session.id,  # Use view_session.id
                class_id=form.class_id.data if form.class_id.data != 0 else None,
                is_active=True
            )
            
            db.session.add(fee_structure)
            db.session.commit()
            
            flash(f'Fee structure "{form.name.data}" created successfully!', 'success')
            return redirect(url_for('manage_fee_structures'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating fee structure: {str(e)}', 'danger')
    
    return render_template('admin_create_fee_structure.html',
                         form=form,
                         context=context)

@app.route('/admin/fee-structures/<int:fee_id>/assign', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def assign_fee_to_students(fee_id):
    """Assign fee structure to students"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = AssignFeeToStudentsForm()
    context = get_school_context()
    
    # Get fee structure
    fee_structure = FeeStructure.query.filter_by(
        id=fee_id,
        school_id=current_user.school_id
    ).first_or_404()
    
    # Populate form
    form.fee_structure_id.choices = [(fee_structure.id, f"{fee_structure.name} - ₹{fee_structure.amount}")]
    
    if form.validate_on_submit():
        try:
            assigned_count = assign_fee_to_all_students(fee_structure.id, form.due_date.data)
            
            flash(f'Fee assigned to {assigned_count} students successfully!', 'success')
            return redirect(url_for('manage_student_fees'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error assigning fee: {str(e)}', 'danger')
    
    return render_template('admin_assign_fee.html',
                         form=form,
                         fee_structure=fee_structure,
                         context=context)

@app.route('/admin/fee-structures/<int:fee_id>/delete', methods=['POST'])
@role_required(['admin'])
@school_active_required
def delete_fee_structure(fee_id):
    """Delete a fee structure"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    fee_structure = FeeStructure.query.filter_by(
        id=fee_id,
        school_id=current_user.school_id
    ).first_or_404()
    
    try:
        # Check if there are any student fees using this structure
        student_fees = StudentFee.query.filter_by(fee_structure_id=fee_id).count()
        
        if student_fees > 0:
            flash(f'Cannot delete fee structure. It is assigned to {student_fees} student(s).', 'danger')
        else:
            db.session.delete(fee_structure)
            db.session.commit()
            flash('Fee structure deleted successfully!', 'success')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting fee structure: {str(e)}', 'danger')
    
    return redirect(url_for('manage_fee_structures'))

@app.route('/admin/fees/students')
@role_required(['admin'])
@school_active_required
def manage_student_fees():
    """Manage student fees and payments"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get search parameters
    status_filter = request.args.get('status', 'all')
    student_id = request.args.get('student_id', '')
    class_id = request.args.get('class_id', '')
    
    # Use view_session instead of current_session
    view_session = context.get('view_session') or context['current_session']
    
    # Base query
    query = StudentFee.query.join(Student).join(FeeStructure).filter(
        Student.school_id == current_user.school_id,
        StudentFee.session_id == view_session.id  # FIXED: Use view_session
    )
    
    # Apply filters
    if status_filter != 'all':
        query = query.filter(StudentFee.status == status_filter)
    
    if student_id:
        query = query.filter(Student.student_id.like(f'%{student_id}%'))
    
    if class_id:
        enrollments = StudentEnrollment.query.filter_by(
            class_id=class_id,
            session_id=view_session.id  # FIXED: Use view_session
        ).subquery()
        query = query.filter(Student.id == enrollments.c.student_id)
    
    student_fees = query.order_by(StudentFee.due_date).all()
    
    # Get summary statistics
    total_fees = sum([fee.fee_amount for fee in student_fees])
    total_paid = sum([fee.paid_amount for fee in student_fees])
    total_due = total_fees - total_paid
    
    # Get class list for filter
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=view_session.id,  # FIXED: Use view_session
        is_active=True
    ).all()
    
    return render_template('admin_manage_student_fees.html',
                         student_fees=student_fees,
                         context=context,
                         total_fees=total_fees,
                         total_paid=total_paid,
                         total_due=total_due,
                         classes=classes,
                         status_filter=status_filter,
                         student_id=student_id,
                         class_id=class_id,
                         date=date.today())  # ADD THIS LINE
# ==================== DEBUG ROUTES ====================

@app.route('/admin/debug/session-check')
@role_required(['admin'])
def debug_session_check():
    """Debug endpoint to check session context and data"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get comprehensive session data
    sessions = AcademicSession.query.filter_by(
        school_id=current_user.school_id,
        is_active=True
    ).order_by(AcademicSession.start_date.desc()).all()
    
    # Get current session details
    current_session = context.get('current_session')
    view_session = context.get('view_session')
    
    # Get all classes for current session
    classes = []
    if current_session:
        classes = Class.query.filter_by(
            school_id=current_user.school_id,
            session_id=current_session.id,
            is_active=True
        ).all()
    
    # Get students count
    total_students = Student.query.filter_by(
        school_id=current_user.school_id,
        is_active=True
    ).count()
    
    # Get enrolled students count for current session
    enrolled_students = 0
    if current_session:
        enrolled_students = StudentEnrollment.query.filter_by(
            session_id=current_session.id,
            is_active=True
        ).count()
    
    # Get fee data
    fee_structures_count = 0
    student_fees_count = 0
    if view_session:
        fee_structures_count = FeeStructure.query.filter_by(
            school_id=current_user.school_id,
            session_id=view_session.id,
            is_active=True
        ).count()
        
        student_fees_count = StudentFee.query.join(Student).filter(
            Student.school_id == current_user.school_id,
            StudentFee.session_id == view_session.id
        ).count()
    
    # Session cookies check
    view_session_id = session.get(f'view_session_{current_user.school_id}')
    
    return render_template('admin_debug_session_check.html',
                         context=context,
                         sessions=sessions,
                         current_session=current_session,
                         view_session=view_session,
                         classes=classes,
                         total_students=total_students,
                         enrolled_students=enrolled_students,
                         fee_structures_count=fee_structures_count,
                         student_fees_count=student_fees_count,
                         view_session_id=view_session_id,
                         current_user=current_user)

# ==================== DEBUG ROUTE TO CHECK DATA ====================

@app.route('/admin/debug/check-data')
@role_required(['admin'])
def debug_check_data():
    """Comprehensive debug endpoint to check all data"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    school_id = current_user.school_id
    
    # Get all sessions
    all_sessions = AcademicSession.query.filter_by(
        school_id=school_id,
        is_active=True
    ).order_by(AcademicSession.start_date.desc()).all()
    
    # Collect data for each session
    session_data = []
    for sess in all_sessions:
        # Get classes for this session
        classes = Class.query.filter_by(
            school_id=school_id,
            session_id=sess.id,
            is_active=True
        ).all()
        
        # Get fee structures for this session
        fee_structures = FeeStructure.query.filter_by(
            school_id=school_id,
            session_id=sess.id,
            is_active=True
        ).all()
        
        # Get student fees for this session
        student_fees = StudentFee.query.join(Student).filter(
            Student.school_id == school_id,
            StudentFee.session_id == sess.id
        ).all()
        
        # Get enrollments for this session
        enrollments = StudentEnrollment.query.filter_by(
            session_id=sess.id,
            is_active=True
        ).all()
        
        session_data.append({
            'session': sess,
            'classes': classes,
            'fee_structures': fee_structures,
            'student_fees': student_fees,
            'enrollments': enrollments
        })
    
    # Check current user's view session
    view_session_id = session.get(f'view_session_{school_id}')
    
    return render_template('admin_debug_check_data.html',
                         context=context,
                         session_data=session_data,
                         view_session_id=view_session_id,
                         school_id=school_id)
@app.route('/admin/debug/fee-stats')
@role_required(['admin'])
def debug_fee_stats():
    """Debug endpoint to check fee statistics"""
    context = get_school_context()
    school_id = current_user.school_id
    view_session = context.get('view_session') or context['current_session']
    
    # Get all student fees
    student_fees = StudentFee.query.join(Student).filter(
        Student.school_id == school_id,
        StudentFee.session_id == view_session.id
    ).all()
    
    # Get all fee structures
    fee_structures = FeeStructure.query.filter_by(
        school_id=school_id,
        session_id=view_session.id
    ).all()
    
    return jsonify({
        'school_id': school_id,
        'view_session': {
            'id': view_session.id,
            'name': view_session.name
        },
        'student_fees_count': len(student_fees),
        'student_fees': [{
            'id': f.id,
            'student_id': f.student_id,
            'student_name': f"{f.student.first_name} {f.student.last_name}",
            'fee_amount': f.fee_amount,
            'discount_amount': f.discount_amount,
            'paid_amount': f.paid_amount,
            'status': f.status,
            'session_id': f.session_id
        } for f in student_fees],
        'fee_structures_count': len(fee_structures),
        'fee_structures': [{
            'id': f.id,
            'name': f.name,
            'amount': f.amount,
            'session_id': f.session_id
        } for f in fee_structures]
    })

@app.route('/admin/debug/fees')
@role_required(['admin'])
def debug_fees():
    """Debug endpoint to check fee data"""
    context = get_school_context()
    view_session = context.get('view_session') or context['current_session']
    
    # Check all fee structures
    fee_structures = FeeStructure.query.filter_by(
        school_id=current_user.school_id,
        session_id=view_session.id
    ).all()
    
    # Check all student fees
    student_fees = StudentFee.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        StudentFee.session_id == view_session.id
    ).all()
    
    return jsonify({
        'school_id': current_user.school_id,
        'session_id': view_session.id,
        'session_name': view_session.name,
        'fee_structures_count': len(fee_structures),
        'fee_structures': [{
            'id': f.id,
            'name': f.name,
            'amount': f.amount,
            'class_id': f.class_id
        } for f in fee_structures],
        'student_fees_count': len(student_fees),
        'student_fees': [{
            'id': f.id,
            'student_id': f.student_id,
            'student_name': f.student.first_name + ' ' + f.student.last_name if f.student else 'Unknown',
            'fee_structure': f.fee_structure.name if f.fee_structure else 'Unknown',
            'amount': f.fee_amount,
            'status': f.status
        } for f in student_fees]
    })

@app.route('/admin/fees/<int:student_fee_id>/payment', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def record_fee_payment(student_fee_id):
    """Record fee payment for a specific student fee"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = RecordPaymentForm()
    context = get_school_context()
    
    # Get student fee record
    student_fee = StudentFee.query.join(Student).filter(
        StudentFee.id == student_fee_id,
        Student.school_id == current_user.school_id
    ).first_or_404()
    
    # Calculate remaining amount
    remaining_amount = student_fee.balance
    
    if form.validate_on_submit():
        try:
            payment_amount = form.amount.data
            
            # Validate payment amount
            if payment_amount <= 0:
                flash('Payment amount must be greater than 0', 'danger')
                return render_template('admin_record_payment.html',
                                     form=form,
                                     student_fee=student_fee,
                                     context=context,
                                     remaining_amount=remaining_amount)
            
            if payment_amount > remaining_amount:
                flash(f'Payment amount cannot exceed remaining amount of ₹{remaining_amount:.2f}', 'danger')
                return render_template('admin_record_payment.html',
                                     form=form,
                                     student_fee=student_fee,
                                     context=context,
                                     remaining_amount=remaining_amount)
            
            # Generate receipt number
            receipt_number = f"RCPT-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
            
            # Create transaction record
            transaction = FeeTransaction(
                student_fee_id=student_fee.id,
                student_id=student_fee.student_id,
                transaction_type='payment',
                amount=payment_amount,
                payment_method=form.payment_method.data,
                transaction_id=form.transaction_id.data or f"TX-{secrets.token_hex(8).upper()}",
                receipt_number=receipt_number,
                status='success',
                created_by=current_user.id,
                transaction_date=datetime.combine(form.payment_date.data, datetime.min.time())
            )
            
            # Update student fee record
            student_fee.paid_amount += payment_amount
            student_fee.payment_method = form.payment_method.data
            student_fee.transaction_id = form.transaction_id.data
            student_fee.payment_date = form.payment_date.data
            student_fee.update_status()  # Update status based on new payment
            
            db.session.add(transaction)
            db.session.commit()
            
            flash(f'Payment of ₹{payment_amount:.2f} recorded successfully! Receipt: {receipt_number}', 'success')
            return redirect(url_for('manage_student_fees'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error recording payment: {str(e)}', 'danger')
    
    return render_template('admin_record_payment.html',
                         form=form,
                         student_fee=student_fee,
                         context=context,
                         remaining_amount=remaining_amount)

@app.route('/admin/fees/record-payment')
@role_required(['admin'])
@school_active_required
def record_fee_payment_redirect():
    """Redirect to select a student fee for payment"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Ensure view_session exists
    if not context.get('view_session'):
        flash('No session selected. Please choose a session.', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Get pending fees (balance > 0) using explicit column arithmetic
    pending_fees = StudentFee.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        StudentFee.session_id == context['view_session'].id,
        (StudentFee.fee_amount - StudentFee.discount_amount + StudentFee.fine_amount - StudentFee.paid_amount) > 0
    ).all()
    
    return render_template('admin_select_fee_for_payment.html',
                         pending_fees=pending_fees,
                         context=context)

@app.route('/admin/fees/discount/apply', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def apply_fee_discount():
    """Apply discount to student fee"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = ApplyDiscountForm()
    context = get_school_context()
    
    # Populate student choices
    students = Student.query.filter_by(
        school_id=current_user.school_id,
        is_active=True
    ).all()
    
    form.student_id.choices = [(s.id, f"{s.student_id} - {s.first_name} {s.last_name}") for s in students]
    
    if form.validate_on_submit():
        try:
            # Create discount record
            discount = FeeDiscount(
                student_id=form.student_id.data,
                discount_type=form.discount_type.data,
                value=form.value.data,
                reason=form.reason.data,
                valid_from=form.valid_from.data,
                valid_to=form.valid_to.data,
                applied_by=current_user.id
            )
            
            db.session.add(discount)
            db.session.commit()
            
            # Apply discount to pending fees
            pending_fees = StudentFee.query.filter(
                StudentFee.student_id == form.student_id.data,
                StudentFee.session_id == context['current_session'].id,
                StudentFee.status.in_(['pending', 'partial']),
                StudentFee.due_date >= form.valid_from.data,
                StudentFee.due_date <= form.valid_to.data
            ).all()
            
            for fee in pending_fees:
                if form.discount_type.data == 'percentage':
                    fee.discount_amount += fee.fee_amount * (form.value.data / 100)
                else:
                    fee.discount_amount += form.value.data
            
            db.session.commit()
            
            flash(f'Discount applied successfully to {len(pending_fees)} fee(s)!', 'success')
            return redirect(url_for('manage_student_fees'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error applying discount: {str(e)}', 'danger')
    
    return render_template('admin_apply_discount.html',
                         form=form,
                         context=context)

@app.route('/admin/fees/reports')
@role_required(['admin'])
@school_active_required
def fee_reports():
    """Generate fee reports"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    view_session = context.get('view_session') or context.get('current_session')
    
    if not view_session:
        flash('No active session found', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Get date range from request or default to current month
    start_date_str = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date_str = request.args.get('end_date', date.today().isoformat())
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = date.today()
    
    # Get ALL student fees (not just transactions) for the view session
    all_student_fees = StudentFee.query.join(Student).join(FeeStructure).filter(
        Student.school_id == current_user.school_id,
        StudentFee.session_id == view_session.id  # Filter by view_session
    ).all()
    
    # Get payment transactions in date range
    transactions = FeeTransaction.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        FeeTransaction.transaction_date >= start_date,
        FeeTransaction.transaction_date <= end_date,
        FeeTransaction.transaction_type == 'payment',
        FeeTransaction.status == 'success'
    ).order_by(FeeTransaction.transaction_date.desc()).all()
    
    # Get summary statistics from all_student_fees
    total_fees = sum([f.fee_amount for f in all_student_fees])
    total_paid = sum([f.paid_amount for f in all_student_fees])
    total_discount = sum([f.discount_amount for f in all_student_fees])
    total_fine = sum([f.fine_amount for f in all_student_fees])
    total_due = sum([f.net_amount - f.paid_amount for f in all_student_fees])
    
    # Get pending fees (unpaid or partially paid)
    pending_fees = [f for f in all_student_fees if f.status in ['pending', 'partial']]
    total_pending = sum([f.net_amount - f.paid_amount for f in pending_fees])
    
    # Get overdue fees
    overdue_fees = [f for f in pending_fees if f.due_date < date.today()]
    total_overdue = sum([f.net_amount - f.paid_amount for f in overdue_fees])
    
    # Get recent transactions for display
    recent_transactions = transactions[:20]  # Limit to 20 for display
    
    return render_template('admin_fee_reports.html',
                         context=context,
                         all_student_fees=all_student_fees,
                         transactions=recent_transactions,
                         total_fees=total_fees,
                         total_paid=total_paid,
                         total_discount=total_discount,
                         total_fine=total_fine,
                         total_due=total_due,
                         total_pending=total_pending,
                         total_overdue=total_overdue,
                         pending_fees_count=len(pending_fees),
                         overdue_fees_count=len(overdue_fees),
                         start_date=start_date,
                         end_date=end_date,
                         view_session=view_session,
                         date=date.today())  # ADD THIS LINE


# ==================== DATA AGGREGATION FUNCTIONS ====================

def get_daily_collection_data(school_id, session_id, days=7):
    """Get daily collection data for the last N days"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days-1)
    
    daily_data = {}
    
    # Generate all dates in range
    current_date = start_date
    while current_date <= end_date:
        daily_data[current_date.strftime('%Y-%m-%d')] = {
            'date': current_date.strftime('%Y-%m-%d'),
            'day': current_date.strftime('%a'),
            'amount': 0
        }
        current_date += timedelta(days=1)
    
    # Get actual transactions
    transactions = FeeTransaction.query.join(Student).filter(
        Student.school_id == school_id,
        FeeTransaction.transaction_date >= start_date,
        FeeTransaction.transaction_date <= end_date,
        FeeTransaction.transaction_type == 'payment',
        FeeTransaction.status == 'success'
    ).all()
    
    # Aggregate by date
    for transaction in transactions:
        date_str = transaction.transaction_date.strftime('%Y-%m-%d')
        if date_str in daily_data:
            daily_data[date_str]['amount'] += float(transaction.amount)
    
    # Convert to list and sort by date
    result = list(daily_data.values())
    result.sort(key=lambda x: x['date'])
    
    return result

def get_payment_method_distribution(school_id, session_id):
    """Get payment method distribution for current session"""
    session = AcademicSession.query.get(session_id)
    if not session:
        return {'labels': [], 'data': [], 'colors': []}
    
    distribution = {}
    
    transactions = FeeTransaction.query.join(Student).filter(
        Student.school_id == school_id,
        FeeTransaction.transaction_date >= session.start_date,
        FeeTransaction.transaction_date <= session.end_date,
        FeeTransaction.transaction_type == 'payment',
        FeeTransaction.status == 'success'
    ).all()
    
    for transaction in transactions:
        method = transaction.payment_method or 'unknown'
        if method not in distribution:
            distribution[method] = 0
        distribution[method] += float(transaction.amount)
    
    # Format for chart
    chart_data = {
        'labels': list(distribution.keys()),
        'data': list(distribution.values()),
        'colors': ['#10b981', '#4f46e5', '#f59e0b', '#8b5cf6', '#64748b', '#ef4444']
    }
    
    return chart_data

def get_monthly_collection_data(school_id, session_id):
    """Get monthly collection data for current session"""
    session = AcademicSession.query.get(session_id)
    if not session:
        return {'labels': [], 'data': []}
    
    # Get start and end months
    start_date = session.start_date
    end_date = session.end_date
    
    # Create month labels
    current_date = start_date.replace(day=1)
    months = []
    monthly_data = {}
    
    while current_date <= end_date:
        month_key = current_date.strftime('%Y-%m')
        month_label = current_date.strftime('%b')
        months.append(month_label)
        monthly_data[month_key] = 0
        # Move to next month
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)
    
    # Get transactions for the session
    transactions = FeeTransaction.query.join(Student).filter(
        Student.school_id == school_id,
        FeeTransaction.transaction_date >= session.start_date,
        FeeTransaction.transaction_date <= session.end_date,
        FeeTransaction.transaction_type == 'payment',
        FeeTransaction.status == 'success'
    ).all()
    
    # Aggregate by month
    for transaction in transactions:
        month_key = transaction.transaction_date.strftime('%Y-%m')
        if month_key in monthly_data:
            monthly_data[month_key] += float(transaction.amount)
    
    # Create sorted data list
    data = []
    current_date = start_date.replace(day=1)
    while current_date <= end_date:
        month_key = current_date.strftime('%Y-%m')
        data.append(float(monthly_data.get(month_key, 0)))
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)
    
    return {
        'labels': months,
        'data': data
    }

def get_class_collection_rates(school_id, session_id):
    """Get collection rates for all classes"""
    classes = Class.query.filter_by(
        school_id=school_id,
        session_id=session_id,
        is_active=True
    ).all()
    
    class_data = []
    
    for class_obj in classes:
        # Get students in this class
        enrollments = StudentEnrollment.query.filter_by(
            class_id=class_obj.id,
            session_id=session_id,
            is_active=True
        ).all()
        
        student_ids = [e.student_id for e in enrollments]
        
        # Get fees for these students
        if student_ids:
            student_fees = StudentFee.query.filter(
                StudentFee.student_id.in_(student_ids),
                StudentFee.session_id == session_id
            ).all()
            
            # Calculate totals
            total_fees = sum([f.fee_amount for f in student_fees])
            total_paid = sum([f.paid_amount for f in student_fees])
            total_discount = sum([f.discount_amount for f in student_fees])
            total_fine = sum([f.fine_amount for f in student_fees])
            total_net = total_fees - total_discount + total_fine
            
            if total_net > 0:
                collection_rate = (total_paid / total_net) * 100
            else:
                collection_rate = 0
            
            class_data.append({
                'class': class_obj,
                'total_fees': total_fees,
                'total_paid': total_paid,
                'total_net': total_net,
                'collection_rate': collection_rate,
                'student_count': len(enrollments)
            })
    
    # Sort by collection rate descending
    class_data.sort(key=lambda x: x['collection_rate'], reverse=True)
    
    return class_data

# Add this function in app.py, near other utility functions
@app.context_processor
def inject_stats():
    """Inject stats into all templates"""
    stats = {}
    
    if current_user.is_authenticated:
        if current_user.is_school_admin or current_user.is_teacher:
            context = get_school_context()
            view_session = context.get('view_session') or context.get('current_session')
            
            if view_session and current_user.school_id:
                stats = get_school_fee_statistics(current_user.school_id, view_session.id)
    
    return {'stats': stats}


def check_fee_assignment_status(school_id, session_id):
    """Check if fee structures have been assigned to students"""
    fee_structures = FeeStructure.query.filter_by(
        school_id=school_id,
        session_id=session_id,
        is_active=True
    ).all()
    
    if not fee_structures:
        return {
            'has_fee_structures': False,
            'message': 'No fee structures found for this session'
        }
    
    assignment_status = []
    for fs in fee_structures:
        student_fees_count = StudentFee.query.filter_by(
            fee_structure_id=fs.id,
            session_id=session_id
        ).count()
        
        assignment_status.append({
            'id': fs.id,
            'name': fs.name,
            'amount': fs.amount,
            'assigned_count': student_fees_count,
            'is_assigned': student_fees_count > 0
        })
    
    return {
        'has_fee_structures': True,
        'fee_structures_count': len(fee_structures),
        'total_assigned': sum([s['assigned_count'] for s in assignment_status]),
        'unassigned_count': len([s for s in assignment_status if not s['is_assigned']]),
        'assignment_status': assignment_status
    }

@app.route('/admin/fees/debug-check')
@role_required(['admin'])
def debug_fee_check():
    """Debug endpoint to check fee data"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    view_session = context.get('view_session') or context.get('current_session')
    
    # Get all fee structures
    fee_structures = FeeStructure.query.filter_by(
        school_id=current_user.school_id,
        session_id=view_session.id
    ).all()
    
    # Get all student fees
    student_fees = StudentFee.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        StudentFee.session_id == view_session.id
    ).all()
    
    # Check assignment status
    assignment_data = []
    for fs in fee_structures:
        assigned_count = StudentFee.query.filter_by(
            fee_structure_id=fs.id,
            session_id=view_session.id
        ).count()
        
        assignment_data.append({
            'fee_structure': fs,
            'assigned_count': assigned_count,
            'students': StudentFee.query.filter_by(
                fee_structure_id=fs.id,
                session_id=view_session.id
            ).all()
        })
    
    return render_template('admin_debug_fee_check.html',
                         context=context,
                         fee_structures=fee_structures,
                         student_fees=student_fees,
                         assignment_data=assignment_data,
                         view_session=view_session)

@app.route('/admin/fees/receipt/<int:transaction_id>')
@role_required(['admin'])
@school_active_required
def generate_fee_receipt(transaction_id):
    """Generate fee receipt"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    transaction = FeeTransaction.query.join(Student).filter(
        FeeTransaction.id == transaction_id,
        Student.school_id == current_user.school_id
    ).first_or_404()
    
    context = get_school_context()
    
    return render_template('admin_fee_receipt.html',
                         transaction=transaction,
                         context=context)

# ==================== STUDENT FEE DASHBOARD ====================

@app.route('/student/fees')
@login_required
@role_required(['student'])
def student_fees():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))

    student = Student.query.filter_by(id=current_user.student_id).first()
    if not student:
        flash('Student record not found', 'danger')
        return redirect(url_for('logout'))

    current_session = get_current_session(student.school_id)
    if not current_session:
        flash('No active session found', 'warning')
        return render_template('student_fees.html',
                               student=student,
                               fees=[],
                               current_session=None,
                               total_due=0,
                               total_paid=0,
                               remaining_due=0,
                               total_discount=0,
                               total_fine=0,
                               overdue_fees=[],
                               recent_transactions=[],
                               date=date.today())

    # Fetch all fees for this student in the current session
    fees = StudentFee.query.filter_by(
        student_id=student.id,
        session_id=current_session.id
    ).order_by(StudentFee.due_date).all()

    # Calculate totals
    total_due = sum(f.fee_amount for f in fees)
    total_paid = sum(f.paid_amount for f in fees)
    total_discount = sum(f.discount_amount for f in fees)
    total_fine = sum(f.fine_amount for f in fees)
    remaining_due = total_due - total_discount + total_fine - total_paid

    # Overdue fees
    today = date.today()
    overdue_fees = [f for f in fees if f.due_date < today and f.status in ['pending', 'partial']]

    # Recent transactions (last 10)
    recent_transactions = FeeTransaction.query.filter_by(
        student_id=student.id
    ).order_by(FeeTransaction.transaction_date.desc()).limit(10).all()

    # Fee structures count (for display, if needed)
    fee_structures_count = FeeStructure.query.filter_by(
        school_id=student.school_id,
        session_id=current_session.id,
        is_active=True
    ).count()

    return render_template('student_fees.html',
                           student=student,
                           fees=fees,
                           current_session=current_session,
                           total_due=total_due,
                           total_paid=total_paid,
                           total_discount=total_discount,
                           total_fine=total_fine,
                           remaining_due=remaining_due,
                           overdue_fees=overdue_fees,
                           recent_transactions=recent_transactions,
                           fee_structures_count=fee_structures_count,
                           date=today)


@app.route('/admin/fees/dashboard')
@role_required(['admin'])
@school_active_required    
def fee_dashboard():
    """Comprehensive fee dashboard with analytics"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    view_session = context.get('view_session') or context['current_session']
    
    if not view_session:
        flash('No active session found', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Get all student fees for the session
    student_fees = StudentFee.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        StudentFee.session_id == view_session.id
    ).all()
    
    # Calculate comprehensive statistics
    stats = {
        'total_fees': sum([f.fee_amount for f in student_fees]),
        'total_paid': sum([f.paid_amount for f in student_fees]),
        'total_discount': sum([f.discount_amount for f in student_fees]),
        'total_fine': sum([f.fine_amount for f in student_fees]),
        'total_due': sum([f.fee_amount - f.discount_amount + f.fine_amount - f.paid_amount 
                         for f in student_fees if f.fee_amount - f.discount_amount + f.fine_amount - f.paid_amount > 0]),
        'student_count': len(set([f.student_id for f in student_fees])),
        'fee_records_count': len(student_fees),
        'paid_students': len(set([f.student_id for f in student_fees if f.status == 'paid'])),
        'partial_students': len(set([f.student_id for f in student_fees if f.status == 'partial'])),
        'pending_students': len(set([f.student_id for f in student_fees if f.status == 'pending'])),
        'overdue_count': len([f for f in student_fees if f.due_date < date.today() and f.status in ['pending', 'partial']])
    }
    
    # Calculate collection rate
    total_net = stats['total_fees'] - stats['total_discount'] + stats['total_fine']
    if total_net > 0:
        stats['collection_rate'] = (stats['total_paid'] / total_net) * 100
    else:
        stats['collection_rate'] = 0
    
    # Get real chart data
    monthly_collection = get_monthly_collection_data(current_user.school_id, view_session.id)
    payment_methods = get_payment_method_distribution(current_user.school_id, view_session.id)
    class_collection = get_class_collection_rates(current_user.school_id, view_session.id)
    
    # Get recent transactions
    recent_transactions = FeeTransaction.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        FeeTransaction.transaction_date >= date.today() - timedelta(days=30)
    ).order_by(FeeTransaction.transaction_date.desc()).limit(10).all()
    
    return render_template('admin_fee_dashboard.html',
                         context=context,
                         stats=stats,
                         class_distribution=class_collection,
                         recent_transactions=recent_transactions,
                         monthly_collection=monthly_collection,
                         payment_methods=payment_methods,
                         date=date.today())

# ==================== TEMPLATE HELPER FUNCTIONS ====================
@app.context_processor
def utility_processor():
    """Make functions available to all templates"""
    def get_overdue_fees_count(school_id):
        """Get count of overdue fees for a school"""
        try:
            from datetime import date
            from models import StudentFee, Student, Class, Session
            
            current_session = Session.query.filter_by(
                school_id=school_id, 
                is_current=True
            ).first()
            
            if not current_session:
                return 0
                
            count = db.session.query(StudentFee).join(Student).filter(
                Student.school_id == school_id,
                StudentFee.session_id == current_session.id,
                StudentFee.due_date < date.today(),
                StudentFee.status.in_(['pending', 'partial'])
            ).count()
            
            return count
        except Exception as e:
            print(f"Error in get_overdue_fees_count: {e}")
            return 0
    
    def get_overdue_fees(school_id, limit=5):
        """Get overdue fees for a school"""
        try:
            from datetime import date
            from models import StudentFee, Student, Class, Session
            
            current_session = Session.query.filter_by(
                school_id=school_id, 
                is_current=True
            ).first()
            
            if not current_session:
                return []
                
            overdue_fees = StudentFee.query.join(Student).filter(
                Student.school_id == school_id,
                StudentFee.session_id == current_session.id,
                StudentFee.due_date < date.today(),
                StudentFee.status.in_(['pending', 'partial'])
            ).order_by(StudentFee.due_date).limit(limit).all()
            
            return overdue_fees
        except Exception as e:
            print(f"Error in get_overdue_fees: {e}")
            return []
    
    def get_student_overdue_fees(student_id):
        """Get overdue fee count for a specific student"""
        try:
            from datetime import date
            from models import StudentFee, Student
            
            student = Student.query.get(student_id)
            if not student:
                return 0
                
            # Get current session for student's school
            from models import Session
            current_session = Session.query.filter_by(
                school_id=student.school_id, 
                is_current=True
            ).first()
            
            if not current_session:
                return 0
                
            count = StudentFee.query.filter_by(
                student_id=student_id,
                session_id=current_session.id
            ).filter(
                StudentFee.due_date < date.today(),
                StudentFee.status.in_(['pending', 'partial'])
            ).count()
            
            return count
        except Exception as e:
            print(f"Error in get_student_overdue_fees: {e}")
            return 0
    
    def get_monthly_collection(school_id, session_id):
        """Get monthly collection data for charts"""
        try:
            from models import FeeTransaction, Student
            from datetime import datetime
            import calendar
            
            # Get transactions for the session year
            session = Session.query.get(session_id)
            if not session:
                return []
            
            year = session.start_date.year
            monthly_data = []
            
            for month in range(1, 13):
                month_start = datetime(year, month, 1)
                if month == 12:
                    month_end = datetime(year + 1, 1, 1)
                else:
                    month_end = datetime(year, month + 1, 1)
                
                total = db.session.query(db.func.coalesce(db.func.sum(FeeTransaction.amount), 0)).join(
                    Student
                ).filter(
                    Student.school_id == school_id,
                    FeeTransaction.transaction_date >= month_start,
                    FeeTransaction.transaction_date < month_end
                ).scalar()
                
                monthly_data.append({
                    'month': calendar.month_abbr[month],
                    'amount': float(total or 0)
                })
            
            return monthly_data
        except Exception as e:
            print(f"Error in get_monthly_collection: {e}")
            # Return empty data for all months
            return [{'month': m, 'amount': 0} for m in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                                                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']]
    
    return {
        'get_overdue_fees_count': get_overdue_fees_count,
        'get_overdue_fees': get_overdue_fees,
        'get_student_overdue_fees': get_student_overdue_fees,
        'get_monthly_collection': get_monthly_collection
    }

# Add session tracking to User model for teachers
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Foreign keys
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=True, unique=True)
    
    # Relationships
    school = db.relationship('School', back_populates='users')
    student = db.relationship('Student', back_populates='user', uselist=False)
    
    # Add this for session management
    current_view_session_id = db.Column(db.Integer, nullable=True)
    
    # ADD THESE METHODS:
    def set_password(self, password):
        """Set password hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.email}>'
    
    # ADD THESE PROPERTIES:
    @property
    def is_developer(self):
        return self.role == 'developer'
    
    @property
    def is_school_admin(self):
        return self.role == 'admin'
    
    @property
    def is_teacher(self):
        return self.role == 'teacher'
    
    @property
    def is_student(self):
        return self.role == 'student'

class ResetTeacherPasswordForm(FlaskForm):
    """Form to reset teacher password"""
    reason = StringField('Reason for Reset', validators=[DataRequired()])
    generate_temporary = BooleanField('Generate Temporary Password', default=True)
    force_logout = BooleanField('Force Logout from All Sessions', default=True)
    notify_via_email = BooleanField('Notify Teacher via Email', default=True)
    submit = SubmitField('Reset Password')

class EditTeacherForm(FlaskForm):
    """Form to edit teacher details"""
    full_name = StringField('Full Name', validators=[DataRequired()])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    phone = StringField('Phone')
    status = SelectField('Account Status', choices=[
        ('active', 'Active'), 
        ('inactive', 'Inactive')
    ], validators=[DataRequired()])
    subjects = StringField('Primary Subjects (comma separated)')
    submit = SubmitField('Update Teacher')

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    address = db.Column(db.Text)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    website = db.Column(db.String(200))
    established_year = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    users = db.relationship('User', back_populates='school')
    sessions = db.relationship('AcademicSession', back_populates='school')
    classes = db.relationship('Class', back_populates='school')
    students = db.relationship('Student', back_populates='school')


class ResetStudentPasswordForm(FlaskForm):
    """Form to reset student password"""
    reason = StringField('Reason for Reset', validators=[DataRequired()])
    generate_temporary = BooleanField('Generate Temporary Password', default=True)
    force_logout = BooleanField('Force Logout from All Sessions', default=True)
    notify_via_email = BooleanField('Notify Student via Email', default=True)
    submit = SubmitField('Reset Password')

class EditStudentForm(FlaskForm):
    """Form to edit student details"""
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    date_of_birth = DateField('Date of Birth', validators=[DataRequired()], format='%Y-%m-%d')
    gender = SelectField('Gender', choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')])
    address = StringField('Address')
    father_name = StringField('Father Name')
    mother_name = StringField('Mother Name')
    phone = StringField('Phone')
    parent_email = EmailField('Parent Email', validators=[Optional(), Email()])
    status = SelectField('Account Status', choices=[
        ('active', 'Active'), 
        ('inactive', 'Inactive')
    ], validators=[DataRequired()])
    submit = SubmitField('Update Student')

@app.route('/student/dashboard')
@role_required(['student'])
def student_dashboard():
    """Student fee dashboard"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    # Get student
    student = Student.query.filter_by(id=current_user.student_id).first()
    if not student:
        flash('Student record not found', 'danger')
        return redirect(url_for('logout'))
    
    # Get current session
    current_session = get_current_session(student.school_id)
    
    if not current_session:
        flash('No active session found', 'warning')
        return render_template('student_dashboard.html',
                             student=student,
                             fees=[],
                             current_session=None,
                             total_due=0,
                             total_paid=0,
                             remaining_due=0,
                             recent_transactions=[],
                             overdue_fees=[],
                             trend_labels=[],
                             trend_data=[],
                             date=date.today())
    
    # Get student fees for current session
    fees = StudentFee.query.filter_by(
        student_id=student.id,
        session_id=current_session.id
    ).order_by(StudentFee.due_date).all()
    
    # Calculate totals
    total_due = sum(f.net_amount for f in fees)
    total_paid = sum(f.paid_amount for f in fees)
    remaining_due = total_due - total_paid
    
    # Get recent transactions (last 6 months)
    six_months_ago = date.today() - timedelta(days=180)
    recent_transactions = FeeTransaction.query.filter(
        FeeTransaction.student_id == student.id,
        FeeTransaction.transaction_date >= six_months_ago
    ).order_by(FeeTransaction.transaction_date.desc()).all()
    
    # Prepare trend data (monthly aggregation)
    from collections import defaultdict
    month_totals = defaultdict(float)
    for txn in recent_transactions:
        month_key = txn.transaction_date.strftime('%b %Y')  # e.g. "Jan 2025"
        month_totals[month_key] += float(txn.amount)
    
    # Sort by date (convert month strings back to datetime for sorting)
    sorted_months = sorted(month_totals.keys(), 
                          key=lambda m: datetime.strptime(m, '%b %Y'))
    trend_labels = sorted_months
    trend_data = [month_totals[m] for m in sorted_months]
    
    # Get overdue fees
    overdue_fees = [f for f in fees if f.is_overdue]
    
    return render_template('student_dashboard.html',
                         student=student,
                         fees=fees,
                         current_session=current_session,
                         total_due=total_due,
                         total_paid=total_paid,
                         remaining_due=remaining_due,
                         recent_transactions=recent_transactions,
                         overdue_fees=overdue_fees,
                         trend_labels=trend_labels,
                         trend_data=trend_data,
                         date=date.today())

class AcademicSession(db.Model):
    __tablename__ = 'academic_sessions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)  # e.g., "2024-2025"
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_current = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    school = db.relationship('School', back_populates='sessions')
    
    # Relationships
    classes = db.relationship('Class', back_populates='session')
    student_enrollments = db.relationship('StudentEnrollment', back_populates='session')
    teacher_assignments = db.relationship('TeacherAssignment', back_populates='session')

class Class(db.Model):
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # e.g., "Class 10A"
    code = db.Column(db.String(20), nullable=False)
    capacity = db.Column(db.Integer, default=40)
    room_number = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    
    # Relationships
    school = db.relationship('School', back_populates='classes')
    session = db.relationship('AcademicSession', back_populates='classes')
    student_enrollments = db.relationship('StudentEnrollment', back_populates='class_')
    teacher_assignments = db.relationship('TeacherAssignment', back_populates='class_')

# In the Student model, update the relationships:
class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    address = db.Column(db.Text)
    father_name = db.Column(db.String(200))
    mother_name = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    parent_email = db.Column(db.String(120))
    photo = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    
    # Enhanced relationships
    school = db.relationship('School', back_populates='students')
    user = db.relationship('User', back_populates='student', uselist=False)
    enrollments = db.relationship('StudentEnrollment', back_populates='student')
    
    # Fee relationships - FIXED with cascade options
    fee_payments = db.relationship('StudentFee', 
                                  back_populates='student',
                                  cascade='all, delete-orphan')
    discounts = db.relationship('FeeDiscount', 
                               back_populates='student',
                               cascade='all, delete-orphan')
    transactions = db.relationship('FeeTransaction', 
                                  back_populates='student',
                                  cascade='all, delete-orphan')
    discounts = db.relationship('FeeDiscount', 
                               back_populates='student',
                               cascade='all, delete-orphan')
    
    # Current class property
    @property
    def current_class(self):
        """Get current class for active session"""
        if not hasattr(self, '_current_class_cache'):
            # Get current enrollment
            current_session = get_current_session(self.school_id)
            if not current_session:
                self._current_class_cache = None
                return None
            
            enrollment = StudentEnrollment.query.filter_by(
                student_id=self.id,
                session_id=current_session.id,
                is_active=True
            ).first()
            
            self._current_class_cache = enrollment.class_ if enrollment else None
        return self._current_class_cache
    
    @property
    def current_enrollment(self):
        """Get current enrollment"""
        current_session = get_current_session(self.school_id)
        if not current_session:
            return None
        
        return StudentEnrollment.query.filter_by(
            student_id=self.id,
            session_id=current_session.id,
            is_active=True
        ).first()

class StudentEnrollment(db.Model):
    __tablename__ = 'student_enrollments'
    id = db.Column(db.Integer, primary_key=True)
    enrollment_date = db.Column(db.Date, nullable=False, default=date.today)
    roll_number = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    
    # Relationships
    student = db.relationship('Student', back_populates='enrollments')
    class_ = db.relationship('Class', back_populates='student_enrollments')
    session = db.relationship('AcademicSession', back_populates='student_enrollments')

class TeacherAssignment(db.Model):
    __tablename__ = 'teacher_assignments'
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    is_class_teacher = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    
    # Relationships
    teacher = db.relationship('User', foreign_keys=[teacher_id])
    class_ = db.relationship('Class', back_populates='teacher_assignments')
    session = db.relationship('AcademicSession', back_populates='teacher_assignments')

# ==================== FORMS ====================

class LoginForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[Optional()])  # Optional for first-time users
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=6, message='Password must be at least 6 characters long')])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('new_password', message='Passwords must match')])
    submit = SubmitField('Change Password')

class CreateSchoolForm(FlaskForm):
    school_name = StringField('School Name', validators=[DataRequired(), Length(min=3, max=200)])
    admin_name = StringField('Admin Name', validators=[DataRequired(), Length(min=3, max=100)])
    admin_email = EmailField('Admin Email', validators=[DataRequired(), Email()])
    address = StringField('Address')
    phone = StringField('Phone')
    email = EmailField('School Email', validators=[Email()])
    website = StringField('Website')
    submit = SubmitField('Create School')

class CreateSessionForm(FlaskForm):
    name = StringField('Session Name (e.g., 2024-2025)', validators=[DataRequired()])
    start_date = DateField('Start Date', validators=[DataRequired()], format='%Y-%m-%d')
    end_date = DateField('End Date', validators=[DataRequired()], format='%Y-%m-%d')
    set_current = BooleanField('Set as Current Session')
    submit = SubmitField('Create Session')

class CreateClassForm(FlaskForm):
    name = StringField('Class Name', validators=[DataRequired()])
    code = StringField('Class Code', validators=[DataRequired()])
    capacity = IntegerField('Capacity', validators=[DataRequired()])
    room_number = StringField('Room Number')
    submit = SubmitField('Create Class')

class CreateTeacherForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired()])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    phone = StringField('Phone')
    subjects = StringField('Subjects (comma separated)')
    submit = SubmitField('Create Teacher')

class CreateStudentForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    date_of_birth = DateField('Date of Birth', validators=[DataRequired()], format='%Y-%m-%d')
    gender = SelectField('Gender', choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')])
    address = StringField('Address')
    father_name = StringField('Father Name')
    mother_name = StringField('Mother Name')
    phone = StringField('Phone')
    parent_email = EmailField('Parent Email', validators=[Optional(), Email()])
    class_id = SelectField('Class', coerce=int, validators=[DataRequired()])
    section = StringField('Section (Optional)', validators=[Optional()])
    submit = SubmitField('Create Student')

class EnrollStudentForm(FlaskForm):
    student_id = SelectField('Student', coerce=int, validators=[DataRequired()])
    class_id = SelectField('Class', coerce=int, validators=[DataRequired()])
    roll_number = IntegerField('Roll Number', validators=[DataRequired()])
    submit = SubmitField('Enroll Student')

class AssignTeacherForm(FlaskForm):
    teacher_id = SelectField('Teacher', coerce=int, validators=[DataRequired()])
    class_id = SelectField('Class', coerce=int, validators=[DataRequired()])
    subject = StringField('Subject', validators=[DataRequired()])
    is_class_teacher = BooleanField('Set as Class Teacher')
    submit = SubmitField('Assign Teacher')

# ==================== UTILITY FUNCTIONS ====================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def generate_password():
    """Generate a random password for new users"""
    return secrets.token_urlsafe(8)

def get_current_session(school_id):
    """Get current active session for school"""
    if not school_id:
        return None
    
    return AcademicSession.query.filter_by(
        school_id=school_id, 
        is_current=True, 
        is_active=True
    ).first()

@app.template_filter('strftime')
def jinja_strftime(value, format='%Y-%m-%d'):
    if value is None:
        return ''
    return value.strftime(format)
def get_view_session(school_id):
    """Get the session user wants to view (from session cookie)"""
    view_session_id = session.get(f'view_session_{school_id}')
    if view_session_id:
        view_session = AcademicSession.query.filter_by(
            id=view_session_id,
            school_id=school_id,
            is_active=True
        ).first()
        if view_session:
            return view_session
    
    # Default to current session
    return get_current_session(school_id)

def get_school_context():
    """Get current school and session context for admin/teacher"""
    if current_user.is_school_admin or current_user.is_teacher:
        school_id = current_user.school_id
        current_session = get_current_session(school_id)
        view_session = get_view_session(school_id)
        
        # Get all sessions for the school
        all_sessions = AcademicSession.query.filter_by(
            school_id=school_id,
            is_active=True
        ).order_by(AcademicSession.start_date.desc()).all()
        
        return {
            'school': current_user.school,
            'current_session': current_session,
            'view_session': view_session,
            'all_sessions': all_sessions
        }
    return {}

@app.route('/student/fees/pay', methods=['POST'])
@login_required
@role_required(['student'])
def student_pay_fee():
    """Simulate fee payment and generate receipt"""
    student = Student.query.get(current_user.student_id)
    if not student:
        return jsonify({'success': False, 'error': 'Student not found'})

    data = request.get_json()
    fee_ids = data.get('fee_ids', [])
    amount = data.get('amount')
    method = data.get('method')

    if not fee_ids or not amount or not method:
        return jsonify({'success': False, 'error': 'Missing data'})

    try:
        # For simulation, we create a transaction record
        receipt_no = f"RCPT-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
        for fee_id in fee_ids:
            fee = StudentFee.query.get(fee_id)
            if fee and fee.student_id == student.id and fee.balance > 0:
                # Create transaction
                transaction = FeeTransaction(
                    student_fee_id=fee.id,
                    student_id=student.id,
                    transaction_type='payment',
                    amount=amount,
                    payment_method=method,
                    transaction_id=f"SIM-{secrets.token_hex(8).upper()}",
                    receipt_number=receipt_no,
                    status='success',
                    created_by=current_user.id,
                    transaction_date=datetime.utcnow()
                )
                # Update fee paid amount
                fee.paid_amount += amount
                fee.update_status()
                db.session.add(transaction)
        db.session.commit()

        return jsonify({
            'success': True,
            'receipt': receipt_no,
            'message': 'Payment recorded successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})
@app.route('/student/fees/statement/pdf')
@login_required
@role_required(['student'])
def student_fee_statement_pdf():
    student = Student.query.get(current_user.student_id)
    fees = StudentFee.query.filter_by(student_id=student.id, session_id=current_session.id).all()
    html = render_template('pdf_fee_statement.html', student=student, fees=fees)
    pdf = weasyprint.HTML(string=html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=fee_statement_{student.student_id}.pdf'
    return response

@app.route('/student/attendance/report/pdf')
@login_required
@role_required(['student'])
def student_attendance_pdf():
    student = Student.query.get(current_user.student_id)
    records = Attendance.query.filter_by(student_id=student.id).order_by(Attendance.date.desc()).all()
    html = render_template('pdf_attendance_report.html', student=student, records=records)
    pdf = weasyprint.HTML(string=html).write_pdf()
    return pdf_response

@app.route('/student/attendance/calendar-data')
@login_required
@role_required(['student'])
def attendance_calendar_data():
    student = Student.query.get(current_user.student_id)
    records = Attendance.query.filter_by(student_id=student.id).all()
    events = []
    for r in records:
        color = '#10b981' if r.status == 'present' else '#ef4444' if r.status == 'absent' else '#f59e0b'
        events.append({
            'title': r.status.capitalize(),
            'start': r.date.isoformat(),
            'color': color
        })
    return jsonify(events)

@app.route('/admin/session/switch/<int:session_id>', methods=['POST'])
@role_required(['admin'])
def switch_view_session(session_id):
    """Switch the view session for admin"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    session_obj = AcademicSession.query.filter_by(
        id=session_id,
        school_id=current_user.school_id,
        is_active=True
    ).first_or_404()
    
    # Store in session cookie
    session[f'view_session_{current_user.school_id}'] = session_obj.id
    
    flash(f'Now viewing session: {session_obj.name}', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/admin/session/switch-to-current', methods=['POST'])
@role_required(['admin'])
def switch_to_current_session():
    """Switch back to current session view"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    # Remove view session from cookie
    session.pop(f'view_session_{current_user.school_id}', None)
    
    flash('Switched to current session view', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/admin/session/<int:session_id>/data')
@role_required(['admin'])
def view_session_data(session_id):
    """View complete data for a specific session"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    session_obj = AcademicSession.query.filter_by(
        id=session_id,
        school_id=current_user.school_id,
        is_active=True
    ).first_or_404()
    
    context = get_school_context()
    
    # Get all data for this session
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=session_id,
        is_active=True
    ).all()
    
    # Get enrollments for this session
    enrollments = StudentEnrollment.query.filter_by(
        session_id=session_id,
        is_active=True
    ).order_by(StudentEnrollment.roll_number).all()
    
    # Get teacher assignments for this session
    teacher_assignments = TeacherAssignment.query.filter_by(
        session_id=session_id
    ).all()
    
    # Organize data by class
    class_data = []
    for class_obj in classes:
        class_enrollments = [e for e in enrollments if e.class_id == class_obj.id]
        class_teachers = [t for t in teacher_assignments if t.class_id == class_obj.id]
        
        class_data.append({
            'class': class_obj,
            'students': class_enrollments,
            'teachers': class_teachers,
            'class_teacher': next((t for t in class_teachers if t.is_class_teacher), None)
        })
    
    # Get all teachers who were active in this session
    teacher_ids = list(set([t.teacher_id for t in teacher_assignments]))
    teachers = User.query.filter(
        User.id.in_(teacher_ids),
        User.school_id == current_user.school_id,
        User.is_active == True
    ).all()
    
    return render_template('admin_view_session_data.html',
                         session_obj=session_obj,
                         context=context,
                         class_data=class_data,
                         teachers=teachers)
# ==================== ROUTES ====================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.must_change_password:
            return redirect(url_for('change_password'))
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('Your account is inactive. Please contact administrator.', 'danger')
                return render_template('auth_login.html', form=form)
            
            # Check if user's school is active (for non-developer users)
            if user.role != 'developer' and user.school_id:
                school = School.query.get(user.school_id)
                if not school or not school.is_active:
                    flash('This school has been suspended. Please contact the system administrator.', 'danger')
                    return render_template('auth_login.html', form=form)
            
            # For students, check if school has current session
            if user.role == 'student':
                current_session = get_current_session(user.school_id)
                if not current_session:
                    flash('Your school does not have an active academic session. Please contact your school administrator.', 'warning')
                    # Still allow login - they'll see a message on dashboard
                    # Don't return here - let them login
            
            login_user(user, remember=form.remember.data)
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            flash('Login successful!', 'success')
            
            # Check if password change is required
            if user.must_change_password:
                return redirect(url_for('change_password'))
            
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('auth_login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    # Check if user is already logged in and trying to access change password when not required
    if not current_user.must_change_password and request.method == 'GET' and 'force' not in request.args:
        # If password doesn't need to be changed and not forced, redirect to dashboard
        flash('Your password is already set.', 'info')
        return redirect(url_for('dashboard'))
    
    form = ChangePasswordForm()
    
    if request.method == 'GET':
        # Pre-populate current_password field only if not first-time change
        if not current_user.must_change_password:
            form.current_password.validators = [DataRequired()]
        else:
            form.current_password.validators = []
    
    if form.validate_on_submit():
        # Check if it's first-time password change
        if current_user.must_change_password:
            # First-time password change - no need to check current password
            if len(form.new_password.data) < 6:
                flash('New password must be at least 6 characters.', 'danger')
            else:
                current_user.set_password(form.new_password.data)
                current_user.must_change_password = False
                db.session.commit()
                flash('Password changed successfully! You can now access the system.', 'success')
                return redirect(url_for('dashboard'))
        
        else:
            # Regular password change - check current password
            if not current_user.check_password(form.current_password.data):
                flash('Current password is incorrect.', 'danger')
            elif len(form.new_password.data) < 6:
                flash('New password must be at least 6 characters.', 'danger')
            else:
                current_user.set_password(form.new_password.data)
                db.session.commit()
                flash('Password changed successfully!', 'success')
                return redirect(url_for('dashboard'))
    
    # Get error messages from form validation
    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')
    
    return render_template('auth_change_password.html', 
                         form=form, 
                         must_change=current_user.must_change_password)

# ==================== DASHBOARD ROUTES ====================

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    if current_user.is_developer:
        return redirect(url_for('developer_dashboard'))
    elif current_user.is_school_admin:
        return redirect(url_for('admin_dashboard'))
    elif current_user.is_teacher:
        return redirect(url_for('teacher_dashboard'))
    elif current_user.is_student:
        return redirect(url_for('student_dashboard'))
    else:
        flash('Unknown user role', 'danger')
        return redirect(url_for('logout'))
    

@app.route('/admin/students/<int:student_id>/reset-password', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def reset_student_password(student_id):
    """Admin resets student password"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get student (must be in same school)
    student = Student.query.filter_by(
        id=student_id,
        school_id=current_user.school_id
    ).first_or_404()
    
    # Get user account
    user = User.query.filter_by(student_id=student.id).first()
    if not user:
        flash('Student user account not found', 'danger')
        return redirect(url_for('manage_students'))
    
    form = ResetStudentPasswordForm()
    
    if form.validate_on_submit():
        try:
            # Generate new password
            if form.generate_temporary.data:
                new_password = secrets.token_urlsafe(8)
            else:
                # Allow admin to set custom password
                new_password = request.form.get('custom_password')
                if not new_password or len(new_password) < 6:
                    flash('Custom password must be at least 6 characters', 'danger')
                    return render_template('admin_reset_student_password.html', 
                                         form=form, student=student, context=context)
            
            # Update student password
            user.set_password(new_password)
            user.must_change_password = True
            
            # Log the action
            from datetime import datetime
            activity_log = {
                'action': 'student_password_reset',
                'admin_id': current_user.id,
                'student_id': student.id,
                'reason': form.reason.data,
                'timestamp': datetime.utcnow().isoformat(),
                'ip_address': request.remote_addr
            }
            
            # Store log in session
            if 'admin_actions' not in session:
                session['admin_actions'] = []
            session['admin_actions'].append(activity_log)
            
            db.session.commit()
            
            # Show success message with password
            if form.generate_temporary.data:
                flash_message = f'Password reset successful for {student.first_name} {student.last_name}! Temporary password: {new_password}'
            else:
                flash_message = f'Password updated successfully for {student.first_name} {student.last_name}!'
            
            flash(flash_message, 'success')
            
            # Email notification (simulated)
            if form.notify_via_email.data:
                flash(f'Email notification would be sent to {student.email} in production.', 'info')
            
            return redirect(url_for('manage_students'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error resetting password: {str(e)}', 'danger')
    
    return render_template('admin_reset_student_password.html', 
                         form=form, student=student, context=context)


@app.route('/admin/students/<int:student_id>/edit', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def edit_student(student_id):
    """Admin edits student details"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get student (must be in same school)
    student = Student.query.filter_by(
        id=student_id,
        school_id=current_user.school_id
    ).first_or_404()
    
    # Get user account
    user = User.query.filter_by(student_id=student.id).first()
    
    form = EditStudentForm()
    
    if request.method == 'GET':
        # Pre-populate form with existing data
        form.first_name.data = student.first_name
        form.last_name.data = student.last_name
        form.date_of_birth.data = student.date_of_birth
        form.gender.data = student.gender
        form.address.data = student.address
        form.father_name.data = student.father_name
        form.mother_name.data = student.mother_name
        form.phone.data = student.phone
        form.parent_email.data = student.parent_email
        form.status.data = 'active' if student.is_active else 'inactive'
    
    if form.validate_on_submit():
        try:
            # Update student details
            student.first_name = form.first_name.data
            student.last_name = form.last_name.data
            student.date_of_birth = form.date_of_birth.data
            student.gender = form.gender.data
            student.address = form.address.data
            student.father_name = form.father_name.data
            student.mother_name.data = form.mother_name.data
            student.phone = form.phone.data
            student.parent_email = form.parent_email.data
            student.is_active = (form.status.data == 'active')
            
            # Update user account if exists
            if user:
                user.full_name = f"{form.first_name.data} {form.last_name.data}"
                user.is_active = (form.status.data == 'active')
            
            # Log the action
            activity_log = {
                'action': 'student_edit',
                'admin_id': current_user.id,
                'student_id': student.id,
                'changes': {
                    'old_name': f"{student.first_name} {student.last_name}",
                    'new_name': f"{form.first_name.data} {form.last_name.data}"
                },
                'timestamp': datetime.utcnow().isoformat(),
                'ip_address': request.remote_addr
            }
            
            if 'admin_actions' not in session:
                session['admin_actions'] = []
            session['admin_actions'].append(activity_log)
            
            db.session.commit()
            
            flash(f'Student {student.first_name} {student.last_name} updated successfully!', 'success')
            return redirect(url_for('manage_students'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating student: {str(e)}', 'danger')
    
    return render_template('admin_edit_student.html', 
                         form=form, student=student, context=context)


@app.route('/admin/students/<int:student_id>/view', methods=['GET'])
@role_required(['admin'])
@school_active_required
def view_student_details(student_id):
    """View complete student details"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get student (must be in same school)
    student = Student.query.filter_by(
        id=student_id,
        school_id=current_user.school_id
    ).first_or_404()
    
    # Get user account
    user = User.query.filter_by(student_id=student.id).first()
    
    # Get all enrollments (historical)
    all_enrollments = StudentEnrollment.query.filter_by(
        student_id=student_id
    ).order_by(StudentEnrollment.session_id.desc()).all()
    
    # Organize enrollments by session
    enrollments_by_session = {}
    for enrollment in all_enrollments:
        session_id = enrollment.session_id
        if session_id not in enrollments_by_session:
            enrollments_by_session[session_id] = []
        enrollments_by_session[session_id].append(enrollment)
    
    # Get session details
    sessions_data = []
    for session_id, enrollments in enrollments_by_session.items():
        session = AcademicSession.query.get(session_id)
        for enrollment in enrollments:
            class_obj = Class.query.get(enrollment.class_id)
            sessions_data.append({
                'session': session,
                'class': class_obj,
                'enrollment': enrollment
            })
    
    # Sort sessions by date (most recent first)
    sessions_data.sort(key=lambda x: x['session'].start_date, reverse=True)
    
    # Get current enrollment
    current_enrollment = None
    if context.get('current_session'):
        current_enrollment = StudentEnrollment.query.filter_by(
            student_id=student_id,
            session_id=context['current_session'].id,
            is_active=True
        ).first()
    
    return render_template('admin_view_student_details.html',
                         student=student,
                         user=user,
                         context=context,
                         current_enrollment=current_enrollment,
                         sessions_data=sessions_data)




# ==================== DEVELOPER ROUTES ====================

@app.route('/developer/dashboard')
@role_required(['developer'])
def developer_dashboard():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    schools = School.query.filter_by(is_active=True).all()
    recent_schools = School.query.order_by(School.created_at.desc()).limit(5).all()
    
    # Calculate real statistics
    total_schools = School.query.filter_by(is_active=True).count()
    active_schools_count = total_schools
    suspended_schools_count = School.query.filter_by(is_active=False).count()
    
    total_admins = User.query.filter_by(role='admin', is_active=True).count()
    active_admins_count = User.query.filter_by(role='admin', is_active=True).count()
    
    total_teachers = User.query.filter_by(role='teacher', is_active=True).count()
    active_teachers_count = total_teachers
    
    total_students = Student.query.filter_by(is_active=True).count()
    
    # Get enrolled students count
    from sqlalchemy import func
    enrolled_students_count = db.session.query(func.count(StudentEnrollment.id)).filter_by(is_active=True).scalar() or 0
    
    # Database status
    try:
        # Test database connection
        db.session.execute('SELECT 1')
        db_connected = True
        db_error = None
    except Exception as e:
        db_connected = False
        db_error = str(e)
    
    # Get database statistics
    db_stats = {
        'total_tables': len(db.metadata.tables),
        'total_records': db.session.query(func.count('*')).select_from(db.metadata.tables['users']).scalar() or 0,
    }
    
    # Get storage usage (estimated)
    import os
    from pathlib import Path
    
    def get_directory_size(path):
        total = 0
        try:
            for entry in os.scandir(path):
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += get_directory_size(entry.path)
        except:
            pass
        return total
    
    # Calculate app directory size
    app_dir = Path(__file__).parent
    try:
        total_size_bytes = get_directory_size(app_dir)
        total_size_gb = total_size_bytes / (1024**3)
    except:
        total_size_gb = 0
    
    # For demo, assume 10GB total storage
    total_storage_gb = 10
    used_storage_gb = round(total_size_gb, 2)
    storage_percentage = min(100, int((used_storage_gb / total_storage_gb) * 100))
    
    # Determine storage color
    if storage_percentage < 70:
        storage_color = 'success'
    elif storage_percentage < 90:
        storage_color = 'warning'
    else:
        storage_color = 'danger'
    
    # Active sessions (simplified - count active users in last 30 minutes)
    from datetime import datetime, timedelta
    thirty_minutes_ago = datetime.utcnow() - timedelta(minutes=30)
    active_sessions_count = User.query.filter(User.last_login >= thirty_minutes_ago).count()
    
    # Recent logins (last 24 hours)
    one_day_ago = datetime.utcnow() - timedelta(days=1)
    recent_logins_count = User.query.filter(User.last_login >= one_day_ago).count()
    
    # System health check
    health_issues = 0
    if not db_connected:
        health_issues += 1
    if storage_percentage > 90:
        health_issues += 1
    
    if health_issues == 0:
        health_status = 'healthy'
        health_color = 'success'
        health_score = 100
    elif health_issues == 1:
        health_status = 'warning'
        health_color = 'warning'
        health_score = 70
    else:
        health_status = 'critical'
        health_color = 'danger'
        health_score = 30
    
    # Recent activity - build from multiple sources
    recent_activity = []
    
    # 1. School creations (last 3)
    recent_schools_for_activity = School.query.order_by(School.created_at.desc()).limit(3).all()
    for school in recent_schools_for_activity:
        # Format time properly
        time_str = school.created_at.strftime('%I:%M %p').lstrip('0')
        recent_activity.append({
            'type': 'school',
            'color': 'primary',
            'icon': 'building',
            'title': 'New School Created',
            'description': f'{school.name} was added to the system',
            'date': school.created_at.strftime('%B %d, %Y'),
            'time': time_str,
            'created_at': school.created_at
        })
    
    # 2. Recent user logins (last 2)
    recent_users = User.query.filter(
        User.last_login.isnot(None),
        User.role != 'developer'
    ).order_by(User.last_login.desc()).limit(2).all()
    
    for user in recent_users:
        school_name = user.school.name if user.school else "System"
        time_str = user.last_login.strftime('%I:%M %p').lstrip('0') if user.last_login else ''
        date_str = user.last_login.strftime('%B %d, %Y') if user.last_login else ''
        
        recent_activity.append({
            'type': 'user',
            'color': 'success',
            'icon': 'person-circle',
            'title': f'{user.full_name} logged in',
            'description': f'{user.role.title()} from {school_name}',
            'date': date_str,
            'time': time_str,
            'created_at': user.last_login
        })
    
    # 3. Recent student enrollments (last 2)
    recent_enrollments = StudentEnrollment.query.order_by(
        StudentEnrollment.created_at.desc()
    ).limit(2).all()
    
    for enrollment in recent_enrollments:
        student_name = f"{enrollment.student.first_name} {enrollment.student.last_name}"
        class_name = enrollment.class_.name if enrollment.class_ else "Unknown Class"
        time_str = enrollment.created_at.strftime('%I:%M %p').lstrip('0')
        
        recent_activity.append({
            'type': 'enrollment',
            'color': 'info',
            'icon': 'person-plus',
            'title': 'Student Enrolled',
            'description': f'{student_name} in {class_name}',
            'date': enrollment.created_at.strftime('%B %d, %Y'),
            'time': time_str,
            'created_at': enrollment.created_at
        })
    
    # Sort all activity by time (most recent first)
    recent_activity.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Statistics for current month
    current_month = datetime.utcnow().month
    current_year = datetime.utcnow().year
    
    new_schools_this_month = School.query.filter(
        db.extract('month', School.created_at) == current_month,
        db.extract('year', School.created_at) == current_year
    ).count()
    
    new_students_this_month = Student.query.filter(
        db.extract('month', Student.created_at) == current_month,
        db.extract('year', Student.created_at) == current_year
    ).count()
    
    new_teachers_this_month = User.query.filter(
        db.extract('month', User.created_at) == current_month,
        db.extract('year', User.created_at) == current_year,
        User.role == 'teacher'
    ).count()
    
    new_classes_this_month = Class.query.filter(
        db.extract('month', Class.created_at) == current_month,
        db.extract('year', Class.created_at) == current_year
    ).count()
    
    # Performance metrics
    performance_metrics = {
        'uptime': 99.8,
        'uptime_trend': 0.1,
        'response_time': 120,
        'response_trend': -5,
        'active_users': active_sessions_count,
        'user_growth': 12,
        'error_rate': 0.2,
        'error_trend': -0.1
    }
    
    stats = {
        'total_schools': total_schools,
        'total_admins': total_admins,
        'total_teachers': total_teachers,
        'total_students': total_students
    }
    
    return render_template('developer_dashboard.html',
                         schools=schools,
                         recent_schools=recent_schools,
                         stats=stats,
                         active_schools_count=active_schools_count,
                         active_admins_count=active_admins_count,
                         active_teachers_count=active_teachers_count,
                         enrolled_students_count=enrolled_students_count,
                         db_status={
                             'connected': db_connected,
                             'error': db_error
                         },
                         db_stats=db_stats,
                         storage_usage={
                             'percentage': storage_percentage,
                             'color': storage_color,
                             'used_gb': used_storage_gb,
                             'total_gb': total_storage_gb
                         },
                         system_health={
                             'status': health_status,
                             'color': health_color,
                             'score': health_score,
                             'issues': health_issues
                         },
                         active_sessions_count=active_sessions_count,
                         recent_logins_count=recent_logins_count,
                         active_sessions_percentage=min(100, (active_sessions_count / max(1, (total_admins + total_teachers))) * 100),
                         recent_activity=recent_activity,
                         stats_by_month={
                             'new_schools': new_schools_this_month,
                             'new_students': new_students_this_month,
                             'new_teachers': new_teachers_this_month,
                             'new_classes': new_classes_this_month
                         },
                         performance_metrics=performance_metrics,
                         report_date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))


# Custom Jinja2 filters for better date/time formatting
@app.template_filter('format_time')
def format_time_filter(value, format='%I:%M %p'):
    """Format time in 12-hour format"""
    if value is None:
        return ''
    try:
        # Remove leading zero from hour if present
        formatted = value.strftime(format)
        if formatted.startswith('0'):
            formatted = formatted[1:]
        return formatted
    except Exception:
        return str(value)

@app.template_filter('format_date')
def format_date_filter(value, format='%B %d, %Y'):
    """Format date nicely"""
    if value is None:
        return ''
    try:
        return value.strftime(format)
    except Exception:
        return str(value)

@app.template_filter('time_ago')
def time_ago_filter(value):
    """Display how long ago something happened"""
    if value is None:
        return 'Unknown time'
    
    now = datetime.utcnow()
    diff = now - value
    
    if diff.days > 365:
        years = diff.days // 365
        return f'{years} year{"s" if years > 1 else ""} ago'
    elif diff.days > 30:
        months = diff.days // 30
        return f'{months} month{"s" if months > 1 else ""} ago'
    elif diff.days > 0:
        return f'{diff.days} day{"s" if diff.days > 1 else ""} ago'
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f'{hours} hour{"s" if hours > 1 else ""} ago'
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f'{minutes} minute{"s" if minutes > 1 else ""} ago'
    else:
        return 'Just now'

@app.route('/developer/schools/create', methods=['GET', 'POST'])
@role_required(['developer'])
def create_school():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = CreateSchoolForm()
    
    if form.validate_on_submit():
        try:
            # Generate unique school code
            school_code = f"SCH-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
            
            # Create school
            school = School(
                name=form.school_name.data,
                code=school_code,
                address=form.address.data,
                phone=form.phone.data,
                email=form.email.data,
                website=form.website.data,
                established_year=datetime.now().year
            )
            db.session.add(school)
            db.session.flush()  # Get school ID
            
            # Generate admin password
            temp_password = generate_password()
            
            # Create admin user
            admin = User(
                email=form.admin_email.data,
                full_name=form.admin_name.data,
                role='admin',
                school_id=school.id,
                must_change_password=True
            )
            admin.set_password(temp_password)
            db.session.add(admin)
            
            # Create default session for current year
            current_year = datetime.now().year
            session_name = f"{current_year}-{current_year + 1}"
            academic_session = AcademicSession(
                name=session_name,
                start_date=date(current_year, 4, 1),  # April 1st
                end_date=date(current_year + 1, 3, 31),  # March 31st next year
                is_current=True,
                school_id=school.id
            )
            db.session.add(academic_session)
            
            db.session.commit()
            
            flash(f'School created successfully! Admin credentials sent to {form.admin_email.data}. Temporary password: {temp_password}', 'success')
            return redirect(url_for('developer_dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating school: {str(e)}', 'danger')
    
    return render_template('developer_create_school.html', form=form)

@app.route('/developer/schools')
@role_required(['developer'])
def manage_schools():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    schools = School.query.filter_by(is_active=True).all()
    return render_template('developer_manage_schools.html', schools=schools)

@app.route('/developer/reset-password/<int:user_id>', methods=['POST'])
@role_required(['developer'])
def reset_password(user_id):
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    user = User.query.get_or_404(user_id)
    
    if user.role != 'developer':  # Cannot reset developer password
        new_password = generate_password()
        user.set_password(new_password)
        user.must_change_password = True
        db.session.commit()
        
        flash(f'Password reset for {user.full_name}. New temporary password: {new_password}', 'success')
    else:
        flash('Cannot reset developer password', 'danger')
    
    return redirect(url_for('developer_dashboard'))

# ==================== SCHOOL ADMIN ROUTES ====================

@app.route('/admin/dashboard')
@role_required(['admin'])
def admin_dashboard():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    # Check if school is suspended
    if current_user.school and not current_user.school.is_active:
        flash('This school has been suspended.', 'danger')
        return redirect(url_for('logout'))
    
    context = get_school_context()
    if not context.get('current_session'):
        flash('No active session found. Create a session first.', 'warning')
        return redirect(url_for('create_session'))
    
    school_id = current_user.school_id
    view_session = context.get('view_session') or context['current_session']
    
    if not view_session:
        flash('No active session found', 'warning')
        return redirect(url_for('create_session'))
    
    # Use the actual function defined in the same file
    stats = get_school_fee_statistics(school_id, view_session.id)
    
    # Additional statistics
    total_students = Student.query.filter_by(
        school_id=school_id, 
        is_active=True
    ).count()
    
    total_teachers = User.query.filter_by(
        school_id=school_id, 
        role='teacher',
        is_active=True
    ).count()
    
    total_classes = Class.query.filter_by(
        school_id=school_id, 
        session_id=view_session.id,
        is_active=True
    ).count()
    
    enrolled_students = StudentEnrollment.query.join(Student).filter(
        Student.school_id == school_id,
        StudentEnrollment.session_id == view_session.id,
        StudentEnrollment.is_active == True
    ).count()
    
    fee_structures_count = FeeStructure.query.filter_by(
        school_id=school_id,
        session_id=view_session.id,
        is_active=True
    ).count()
    
    # Get class-wise distribution
    classes = Class.query.filter_by(
        school_id=school_id,
        session_id=view_session.id,
        is_active=True
    ).all()
    
    class_distribution = []
    for class_obj in classes:
        enrollments = StudentEnrollment.query.filter_by(
            class_id=class_obj.id,
            session_id=view_session.id,
            is_active=True
        ).all()
        
        student_ids = [e.student_id for e in enrollments]
        
        if student_ids:
            class_fees = StudentFee.query.filter(
                StudentFee.student_id.in_(student_ids),
                StudentFee.session_id == view_session.id
            ).all()
            
            class_total_fees = sum([f.fee_amount for f in class_fees]) if class_fees else 0
            class_total_paid = sum([f.paid_amount for f in class_fees]) if class_fees else 0
            class_total_discount = sum([f.discount_amount for f in class_fees]) if class_fees else 0
            class_total_fine = sum([f.fine_amount for f in class_fees]) if class_fees else 0
            class_total_net = class_total_fees - class_total_discount + class_total_fine
            class_total_due = max(0, class_total_net - class_total_paid)
            class_collection_rate = (class_total_paid / class_total_net * 100) if class_total_net > 0 else 0
        else:
            class_collection_rate = 0
        
        class_distribution.append({
            'class': class_obj,
            'total_fees': class_total_fees,
            'total_paid': class_total_paid,
            'total_discount': class_total_discount,
            'total_fine': class_total_fine,
            'total_due': class_total_due,
            'student_count': len(enrollments),
            'collection_rate': class_collection_rate
        })
    
    # Get recent fee transactions
    recent_transactions = FeeTransaction.query.join(Student).filter(
        Student.school_id == school_id
    ).order_by(FeeTransaction.transaction_date.desc()).limit(10).all()
    
    # Get overdue fees
    overdue_fees = StudentFee.query.join(Student).filter(
        Student.school_id == school_id,
        StudentFee.session_id == view_session.id,
        StudentFee.due_date < date.today(),
        StudentFee.status.in_(['pending', 'partial'])
    ).limit(10).all()
    
    # Calculate overdue amount
    overdue_amount = sum([(f.fee_amount - f.discount_amount + f.fine_amount - f.paid_amount) 
                         for f in overdue_fees])
    
    # Get recent activities
    recent_activities = []
    
    # Recent fee payments
    for transaction in recent_transactions[:5]:
        recent_activities.append({
            'title': 'Fee Payment Received',
            'description': f'{transaction.student.first_name} {transaction.student.last_name} - ₹{transaction.amount}',
            'time': transaction.transaction_date.strftime('%H:%M'),
            'icon': 'fa-money-bill-wave',
            'color': 'success'
        })
    
    # Recent student enrollments
    recent_enrollments = StudentEnrollment.query.join(Student).filter(
        Student.school_id == school_id,
        StudentEnrollment.session_id == view_session.id
    ).order_by(StudentEnrollment.created_at.desc()).limit(3).all()
    
    for enrollment in recent_enrollments:
        recent_activities.append({
            'title': 'Student Enrolled',
            'description': f'{enrollment.student.first_name} {enrollment.student.last_name} in Class {enrollment.class_.name}',
            'time': enrollment.created_at.strftime('%H:%M'),
            'icon': 'fa-user-plus',
            'color': 'info'
        })
    
    # Get real chart data for last 7 days
    daily_collection = get_daily_collection_data(school_id, view_session.id, days=7)
    
    # Prepare data for fee chart
    chart_labels = [item['day'] for item in daily_collection]
    chart_data = [item['amount'] for item in daily_collection]
    
    # Get payment method distribution
    payment_methods_data = get_payment_method_distribution(school_id, view_session.id)
    
    # Use the new premium template
    return render_template('admin_dashboard_premium.html',
                         context=context,
                         stats=stats,
                         total_students=total_students,
                         total_teachers=total_teachers,
                         total_classes=total_classes,
                         enrolled_students=enrolled_students,
                         fee_structures_count=fee_structures_count,
                         classes=classes,
                         class_distribution=class_distribution,
                         recent_transactions=recent_transactions,
                         overdue_fees=overdue_fees,
                         overdue_amount=overdue_amount,
                         recent_activities=recent_activities,
                         chart_labels=chart_labels,
                         chart_data=chart_data,
                         payment_methods_data=payment_methods_data,
                         date=date.today())

# ==================== ENHANCED FEE MANAGEMENT ROUTES ====================
def get_session_context():
    """Get consistent session context for fee management"""
    context = get_school_context()
    
    # Ensure we have a view session
    if not context.get('view_session'):
        context['view_session'] = context.get('current_session')
    
    # If still no session, get the latest active session
    if not context.get('view_session'):
        latest_session = AcademicSession.query.filter_by(
            school_id=current_user.school_id,
            is_active=True
        ).order_by(AcademicSession.start_date.desc()).first()
        
        if latest_session:
            context['view_session'] = latest_session
            # Store in session cookie for consistency
            session[f'view_session_{current_user.school_id}'] = latest_session.id
    
    return context


@app.route('/admin/fees/manage')
@role_required(['admin'])
@school_active_required
def manage_fees():
    """Enhanced fee management dashboard"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    view_session = context.get('view_session') or context['current_session']
    
    if not view_session:
        flash('No active session found', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Get fee structures
    fee_structures = FeeStructure.query.filter_by(
        school_id=current_user.school_id,
        session_id=view_session.id,
        is_active=True
    ).all()
    
    # Get all student fees for the session
    student_fees = StudentFee.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        StudentFee.session_id == view_session.id
    ).all()
    
    # Calculate statistics
    total_fees = sum([f.fee_amount for f in student_fees])
    total_collected = sum([f.paid_amount for f in student_fees])
    total_discount = sum([f.discount_amount for f in student_fees])
    total_fine = sum([f.fine_amount for f in student_fees])
    total_pending = sum([(f.fee_amount - f.discount_amount + f.fine_amount - f.paid_amount) 
                        for f in student_fees if f.status in ['pending', 'partial']])
    
    # Calculate overdue fees
    overdue_fees = [f for f in student_fees if f.due_date < date.today() and f.status in ['pending', 'partial']]
    total_overdue = sum([(f.fee_amount - f.discount_amount + f.fine_amount - f.paid_amount) 
                        for f in overdue_fees])
    
    # Calculate collection rate
    collection_rate = (total_collected / (total_fees - total_discount + total_fine) * 100) if (total_fees - total_discount + total_fine) > 0 else 0
    
    # Get class-wise fee summary
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=view_session.id,
        is_active=True
    ).all()
    
    class_fee_summary = []
    for class_obj in classes:
        # Get students in this class
        enrollments = StudentEnrollment.query.filter_by(
            class_id=class_obj.id,
            session_id=view_session.id,
            is_active=True
        ).all()
        
        student_ids = [e.student_id for e in enrollments]
        
        # Get fees for these students
        class_student_fees = StudentFee.query.filter(
            StudentFee.student_id.in_(student_ids),
            StudentFee.session_id == view_session.id
        ).all()
        
        if class_student_fees:
            class_total_fees = sum([f.fee_amount for f in class_student_fees])
            class_total_collected = sum([f.paid_amount for f in class_student_fees])
            class_total_discount = sum([f.discount_amount for f in class_student_fees])
            class_total_fine = sum([f.fine_amount for f in class_student_fees])
            class_total_due = class_total_fees - class_total_collected - class_total_discount + class_total_fine
            
            class_collection_rate = (class_total_collected / (class_total_fees - class_total_discount + class_total_fine) * 100) if (class_total_fees - class_total_discount + class_total_fine) > 0 else 0
            
            class_fee_summary.append({
                'id': class_obj.id,
                'name': class_obj.name,
                'code': class_obj.code,
                'total_students': len(enrollments),
                'total_fees': class_total_fees,
                'total_collected': class_total_collected,
                'total_due': class_total_due,
                'collection_rate': class_collection_rate
            })
    
    return render_template('admin_fee_management.html',
                         context=context,
                         fee_structures=fee_structures,
                         total_fees=total_fees,
                         total_collected=total_collected,
                         total_pending=total_pending,
                         total_overdue=total_overdue,
                         pending_count=len([f for f in student_fees if f.status in ['pending', 'partial']]),
                         overdue_count=len(overdue_fees),
                         collection_rate=collection_rate,
                         class_fee_summary=class_fee_summary)

@app.route('/admin/fees/assign/bulk', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def assign_fee_to_students_bulk():
    """Bulk assign fees to multiple classes or all students"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    view_session = context.get('view_session') or context['current_session']
    
    if not view_session:
        flash('No active session found', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        try:
            fee_structure_id = request.form.get('fee_structure_id')
            class_ids = request.form.getlist('class_ids')
            due_date = request.form.get('due_date')
            
            if not fee_structure_id or not due_date:
                flash('Please fill all required fields', 'danger')
                return redirect(request.url)
            
            # Get fee structure
            fee_structure = FeeStructure.query.filter_by(
                id=fee_structure_id,
                school_id=current_user.school_id,
                session_id=view_session.id
            ).first_or_404()
            
            # Parse date
            due_date_obj = datetime.strptime(due_date, '%Y-%m-%d').date()
            
            assigned_count = 0
            
            if 'all' in class_ids:
                # Assign to all active students
                students = Student.query.filter_by(
                    school_id=current_user.school_id,
                    is_active=True
                ).all()
                
                for student in students:
                    # Check if fee already assigned
                    existing_fee = StudentFee.query.filter_by(
                        student_id=student.id,
                        fee_structure_id=fee_structure.id,
                        session_id=view_session.id
                    ).first()
                    
                    if not existing_fee:
                        student_fee = StudentFee(
                            student_id=student.id,
                            fee_structure_id=fee_structure.id,
                            session_id=view_session.id,
                            fee_amount=fee_structure.amount,
                            discount_amount=0,
                            fine_amount=0,
                            paid_amount=0,
                            due_date=due_date_obj,
                            status='pending'
                        )
                        db.session.add(student_fee)
                        assigned_count += 1
            
            else:
                # Assign to specific classes
                for class_id in class_ids:
                    if class_id == 'all':
                        continue
                    
                    # Get all students in this class
                    enrollments = StudentEnrollment.query.filter_by(
                        class_id=class_id,
                        session_id=view_session.id,
                        is_active=True
                    ).all()
                    
                    for enrollment in enrollments:
                        student = enrollment.student
                        
                        # Check if fee already assigned
                        existing_fee = StudentFee.query.filter_by(
                            student_id=student.id,
                            fee_structure_id=fee_structure.id,
                            session_id=view_session.id
                        ).first()
                        
                        if not existing_fee:
                            student_fee = StudentFee(
                                student_id=student.id,
                                fee_structure_id=fee_structure.id,
                                session_id=view_session.id,
                                fee_amount=fee_structure.amount,
                                discount_amount=0,
                                fine_amount=0,
                                paid_amount=0,
                                due_date=due_date_obj,
                                status='pending'
                            )
                            db.session.add(student_fee)
                            assigned_count += 1
            
            db.session.commit()
            
            flash(f'Fee assigned to {assigned_count} students successfully!', 'success')
            return redirect(url_for('manage_fees'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error assigning fees: {str(e)}', 'danger')
    
    # GET request - show form
    fee_structures = FeeStructure.query.filter_by(
        school_id=current_user.school_id,
        session_id=view_session.id,
        is_active=True
    ).all()
    
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=view_session.id,
        is_active=True
    ).all()
    
    # FIX: Add date to the template context
    return render_template('admin_bulk_assign_fees.html',
                         context=context,
                         fee_structures=fee_structures,
                         classes=classes,
                         date=date.today())  # Add this line

@app.route('/admin/fees/class/<int:class_id>/details')
@role_required(['admin'])
@school_active_required
def class_fee_details(class_id):
    """View detailed fee information for a class"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    view_session = context.get('view_session') or context['current_session']
    
    # Get class
    class_obj = Class.query.filter_by(
        id=class_id,
        school_id=current_user.school_id,
        session_id=view_session.id
    ).first_or_404()
    
    # Get students in this class
    enrollments = StudentEnrollment.query.filter_by(
        class_id=class_id,
        session_id=view_session.id,
        is_active=True
    ).order_by(StudentEnrollment.roll_number).all()
    
    # Get fee structures for this class
    class_fee_structures = FeeStructure.query.filter(
        FeeStructure.school_id == current_user.school_id,
        FeeStructure.session_id == view_session.id,
        or_(
            FeeStructure.class_id == class_id,
            FeeStructure.class_id.is_(None)
        ),
        FeeStructure.is_active == True
    ).all()
    
    # Get student fees
    student_data = []
    for enrollment in enrollments:
        student = enrollment.student
        student_fees = StudentFee.query.filter_by(
            student_id=student.id,
            session_id=view_session.id
        ).all()
        
        total_fees = sum([f.fee_amount for f in student_fees])
        total_paid = sum([f.paid_amount for f in student_fees])
        total_discount = sum([f.discount_amount for f in student_fees])
        total_fine = sum([f.fine_amount for f in student_fees])
        balance_due = total_fees - total_paid - total_discount + total_fine
        
        student_data.append({
            'student': student,
            'enrollment': enrollment,
            'fees': student_fees,
            'total_fees': total_fees,
            'total_paid': total_paid,
            'balance_due': balance_due,
            'status': 'paid' if balance_due <= 0 else 'partial' if total_paid > 0 else 'pending'
        })
    
    # Calculate class totals
    class_total_fees = sum([s['total_fees'] for s in student_data])
    class_total_paid = sum([s['total_paid'] for s in student_data])
    class_balance_due = sum([s['balance_due'] for s in student_data])
    class_collection_rate = (class_total_paid / class_total_fees * 100) if class_total_fees > 0 else 0
    
    return render_template('admin_class_fee_details.html',
                         context=context,
                         class_obj=class_obj,
                         student_data=student_data,
                         fee_structures=class_fee_structures,
                         class_total_fees=class_total_fees,
                         class_total_paid=class_total_paid,
                         class_balance_due=class_balance_due,
                         class_collection_rate=class_collection_rate)

@app.route('/admin/fees/analytics')
@role_required(['admin'])
@school_active_required
def fee_analytics():
    """Advanced fee analytics with charts"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    view_session = context.get('view_session') or context['current_session']
    
    if not view_session:
        flash('No active session found', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Get date range
    start_date_str = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date_str = request.args.get('end_date', date.today().isoformat())
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = date.today()
    
    # Get all student fees
    student_fees = StudentFee.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        StudentFee.session_id == view_session.id
    ).all()
    
    # Calculate statistics
    total_fees = sum([f.fee_amount for f in student_fees])
    total_paid = sum([f.paid_amount for f in student_fees])
    total_discount = sum([f.discount_amount for f in student_fees])
    total_fine = sum([f.fine_amount for f in student_fees])
    total_due = total_fees - total_paid - total_discount + total_fine
    
    # Get transactions for date range
    transactions = FeeTransaction.query.join(Student).filter(
        Student.school_id == current_user.school_id,
        FeeTransaction.transaction_date >= start_date,
        FeeTransaction.transaction_date <= end_date,
        FeeTransaction.status == 'success'
    ).order_by(FeeTransaction.transaction_date).all()
    
    # Prepare data for charts
    # Daily collection data
    daily_data = {}
    for transaction in transactions:
        date_str = transaction.transaction_date.strftime('%Y-%m-%d')
        if date_str not in daily_data:
            daily_data[date_str] = 0
        daily_data[date_str] += transaction.amount
    
    # Payment method distribution
    method_data = {}
    for transaction in transactions:
        method = transaction.payment_method or 'unknown'
        if method not in method_data:
            method_data[method] = 0
        method_data[method] += transaction.amount
    
    # Class-wise collection
    class_data = {}
    for transaction in transactions:
        if transaction.student_fee and transaction.student_fee.class_info:
            class_name = transaction.student_fee.class_info.name
        else:
            class_name = 'Unknown'
        
        if class_name not in class_data:
            class_data[class_name] = 0
        class_data[class_name] += transaction.amount
    
    return render_template('admin_fee_analytics.html',
                         context=context,
                         start_date=start_date,
                         end_date=end_date,
                         total_fees=total_fees,
                         total_paid=total_paid,
                         total_due=total_due,
                         total_discount=total_discount,
                         total_fine=total_fine,
                         daily_data=daily_data,
                         method_data=method_data,
                         class_data=class_data,
                         transactions=transactions)

# Update the CreateFeeStructureForm to handle class selection better
class EnhancedCreateFeeStructureForm(FlaskForm):
    name = StringField('Fee Name', validators=[DataRequired()])
    description = StringField('Description')
    amount = FloatField('Amount', validators=[DataRequired()])
    frequency = SelectField('Frequency', choices=[
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('half-yearly', 'Half Yearly'),
        ('yearly', 'Yearly'),
        ('one-time', 'One Time')
    ], validators=[DataRequired()])
    applicable_to = SelectField('Applicable To', choices=[
        ('all', 'All Classes'),
        ('specific', 'Specific Class')
    ], validators=[DataRequired()])
    class_id = SelectField('Class', coerce=int, validators=[Optional()])
    submit = SubmitField('Create Fee Structure')


@app.route('/admin/debug/fees-view')
@role_required(['admin'])
def debug_fees_view():
    """Debug endpoint to check fee data in dashboard"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    school_id = current_user.school_id
    view_session = context['view_session']
    
    # Get all student fees
    student_fees = StudentFee.query.join(Student).filter(
        Student.school_id == school_id,
        StudentFee.session_id == view_session.id
    ).all()
    
    # Get all fee structures
    fee_structures = FeeStructure.query.filter_by(
        school_id=school_id,
        session_id=view_session.id,
        is_active=True
    ).all()
    
    return render_template('admin_debug_fees.html',
                         context=context,
                         student_fees=student_fees,
                         fee_structures=fee_structures,
                         student_fees_count=len(student_fees),
                         fee_structures_count=len(fee_structures))

@app.route('/admin/fees/create-test-transactions', methods=['POST'])
@role_required(['admin'])
def create_test_transactions():
    """Create test fee transactions for debugging"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    try:
        context = get_school_context()
        school_id = current_user.school_id
        
        # Get first 5 students
        students = Student.query.filter_by(
            school_id=school_id, 
            is_active=True
        ).limit(5).all()
        
        created_count = 0
        for i, student in enumerate(students):
            # Create a test transaction for each student
            transaction = FeeTransaction(
                student_id=student.id,
                transaction_type='payment',
                amount=1000.0 * (i + 1),  # Different amounts for each
                payment_method=['cash', 'bank_transfer', 'online', 'card', 'check'][i % 5],
                transaction_id=f"TEST-TX-{secrets.token_hex(8).upper()}",
                transaction_date=date.today() - timedelta(days=i),  # Different dates
                status='success',
                receipt_number=f"RCPT-TEST-{datetime.now().strftime('%Y%m%d')}-{i+1}",
                created_by=current_user.id
            )
            db.session.add(transaction)
            created_count += 1
        
        db.session.commit()
        
        flash(f'Created {created_count} test transactions successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating test transactions: {str(e)}', 'danger')
    
    return redirect(url_for('fee_reports'))
@app.route('/admin/sessions/create', methods=['GET', 'POST'])
@role_required(['admin'])
def create_session():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = CreateSessionForm()
    context = get_school_context()
    
    if form.validate_on_submit():
        try:
            # Check if session name already exists for this school
            existing = AcademicSession.query.filter_by(
                school_id=current_user.school_id,
                name=form.name.data
            ).first()
            
            if existing:
                flash('Session with this name already exists', 'danger')
            else:
                # If setting as current, unset current from other sessions
                if form.set_current.data:
                    AcademicSession.query.filter_by(
                        school_id=current_user.school_id,
                        is_current=True
                    ).update({'is_current': False})
                
                # Create new session
                new_session = AcademicSession(
                    name=form.name.data,
                    start_date=form.start_date.data,
                    end_date=form.end_date.data,
                    is_current=form.set_current.data,
                    school_id=current_user.school_id
                )
                db.session.add(new_session)
                db.session.flush()  # Get the session ID
                
                # Copy classes from previous session if requested
                if request.form.get('copy_classes'):
                    previous_session = AcademicSession.query.filter_by(
                        school_id=current_user.school_id,
                        is_current=True
                    ).first()
                    
                    if previous_session:
                        previous_classes = Class.query.filter_by(
                            school_id=current_user.school_id,
                            session_id=previous_session.id,
                            is_active=True
                        ).all()
                        
                        for prev_class in previous_classes:
                            new_class = Class(
                                name=prev_class.name,
                                code=f"{prev_class.code}-NEW",  # Modify code for new session
                                capacity=prev_class.capacity,
                                room_number=prev_class.room_number,
                                school_id=current_user.school_id,
                                session_id=new_session.id
                            )
                            db.session.add(new_class)
                
                # Copy teacher assignments if requested
                if request.form.get('copy_teachers'):
                    previous_session = AcademicSession.query.filter_by(
                        school_id=current_user.school_id,
                        is_current=True
                    ).first()
                    
                    if previous_session:
                        previous_assignments = TeacherAssignment.query.filter_by(
                            session_id=previous_session.id
                        ).all()
                        
                        for assignment in previous_assignments:
                            new_assignment = TeacherAssignment(
                                teacher_id=assignment.teacher_id,
                                class_id=None,  # Will need to map to new class IDs
                                session_id=new_session.id,
                                subject=assignment.subject,
                                is_class_teacher=assignment.is_class_teacher
                            )
                            db.session.add(new_assignment)
                
                db.session.commit()
                
                flash(f'Session created successfully! Session: {new_session.name}', 'success')
                
                if new_session.is_current:
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect(url_for('manage_sessions'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating session: {str(e)}', 'danger')
    
    return render_template('admin_create_session.html', form=form, context=context)

@app.route('/admin/sessions')
@role_required(['admin'])
def manage_sessions():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    sessions = AcademicSession.query.filter_by(
        school_id=current_user.school_id,
        is_active=True
    ).order_by(AcademicSession.start_date.desc()).all()
    
    return render_template('admin_manage_sessions.html', 
                         sessions=sessions, 
                         context=context)

@app.route('/admin/sessions/switch/<int:session_id>', methods=['POST'])
@role_required(['admin'])
def switch_session(session_id):
    """Make a different session the current session"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    session_obj = AcademicSession.query.filter_by(
        id=session_id,
        school_id=current_user.school_id
    ).first_or_404()
    
    # Unset current from all sessions
    AcademicSession.query.filter_by(
        school_id=current_user.school_id,
        is_current=True
    ).update({'is_current': False})
    
    # Set selected session as current
    session_obj.is_current = True
    
    # Clear any view session settings
    session.pop(f'view_session_{current_user.school_id}', None)
    
    db.session.commit()
    
    flash(f'Switched to session: {session_obj.name}. This is now the current session.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/classes/create', methods=['GET', 'POST'])
@role_required(['admin'])
def create_class():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = CreateClassForm()
    context = get_school_context()
    
    if not context.get('current_session'):
        flash('No active session. Please create or select a session first.', 'warning')
        return redirect(url_for('create_session'))
    
    if form.validate_on_submit():
        try:
            # Check if class code already exists in this session
            existing = Class.query.filter_by(
                school_id=current_user.school_id,
                session_id=context['current_session'].id,
                code=form.code.data
            ).first()
            
            if existing:
                flash('Class with this code already exists in current session', 'danger')
            else:
                class_obj = Class(
                    name=form.name.data,
                    code=form.code.data,
                    capacity=form.capacity.data,
                    room_number=form.room_number.data,
                    school_id=current_user.school_id,
                    session_id=context['current_session'].id
                )
                db.session.add(class_obj)
                db.session.commit()
                
                flash('Class created successfully!', 'success')
                return redirect(url_for('manage_classes'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating class: {str(e)}', 'danger')
    
    return render_template('admin_create_class.html', form=form, context=context)

@app.route('/admin/classes')
@role_required(['admin'])
def manage_classes():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    if not context.get('current_session'):
        flash('No active session. Please create or select a session first.', 'warning')
        return redirect(url_for('create_session'))
    
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=context['current_session'].id,
        is_active=True
    ).all()
    
    return render_template('admin_manage_classes.html', 
                         classes=classes, 
                         context=context)

@app.route('/admin/teachers/create', methods=['GET', 'POST'])
@role_required(['admin'])
def create_teacher():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = CreateTeacherForm()
    context = get_school_context()
    
    if form.validate_on_submit():
        try:
            # Check if email already exists
            existing = User.query.filter_by(email=form.email.data).first()
            if existing:
                flash('Email already registered', 'danger')
            else:
                # Generate temporary password
                temp_password = generate_password()
                
                # Create teacher user
                teacher = User(
                    email=form.email.data,
                    full_name=form.full_name.data,
                    phone=form.phone.data,
                    role='teacher',
                    school_id=current_user.school_id,
                    must_change_password=True
                )
                teacher.set_password(temp_password)
                db.session.add(teacher)
                db.session.commit()
                
                flash(f'Teacher created successfully! Temporary password: {temp_password}', 'success')
                return redirect(url_for('manage_teachers'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating teacher: {str(e)}', 'danger')
    
    return render_template('admin_create_teacher.html', form=form, context=context)

@app.route('/admin/teachers')
@role_required(['admin'])
def manage_teachers():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    teachers = User.query.filter_by(
        school_id=current_user.school_id,
        role='teacher',
        is_active=True
    ).all()
    
    # Get assigned classes for each teacher
    teacher_data = []
    for teacher in teachers:
        assignments = TeacherAssignment.query.filter_by(teacher_id=teacher.id).all()
        assigned_classes = [ass.class_ for ass in assignments if ass.class_.session_id == context['current_session'].id]
        teacher_data.append({
            'teacher': teacher,
            'assigned_classes': assigned_classes,
            'subjects': ', '.join(set([ass.subject for ass in assignments]))
        })
    
    return render_template('admin_manage_teachers.html', 
                         teacher_data=teacher_data, 
                         context=context)

@app.route('/admin/students/create', methods=['GET', 'POST'])
@role_required(['admin'])
def create_student():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = CreateStudentForm()
    context = get_school_context()
    
    if not context.get('current_session'):
        flash('No active session. Please create or select a session first.', 'warning')
        return redirect(url_for('create_session'))
    
    # Populate class choices
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=context['current_session'].id,
        is_active=True
    ).all()
    
    if not classes:
        flash('No classes available. Please create a class first.', 'danger')
        return redirect(url_for('create_class'))
    
    form.class_id.choices = [(c.id, f"{c.name} ({c.code})") for c in classes]
    
    if form.validate_on_submit():
        try:
            # Generate unique student ID
            year_code = datetime.now().strftime('%y')
            school_code = current_user.school.code[:3].upper() if current_user.school.code else 'SCH'
            random_code = secrets.token_hex(2).upper()
            student_id = f"STU-{year_code}-{school_code}-{random_code}"
            
            # Check if student ID already exists
            existing = Student.query.filter_by(student_id=student_id).first()
            if existing:
                random_code = secrets.token_hex(2).upper()
                student_id = f"STU-{year_code}-{school_code}-{random_code}"
            
            # Generate unique school email for student
            school_domain = "schoolerp.com"
            if current_user.school.email and '@' in current_user.school.email:
                school_domain = current_user.school.email.split('@')[1]
            
            import re
            first_name_clean = re.sub(r'[^a-zA-Z]', '', form.first_name.data).lower()
            last_name_clean = re.sub(r'[^a-zA-Z]', '', form.last_name.data).lower()
            base_email = f"{first_name_clean}.{last_name_clean}.{student_id.lower()}"
            base_email = re.sub(r'[^a-zA-Z0-9._-]', '', base_email)
            student_email = f"{base_email}@{school_domain}"
            
            # Check if email already exists
            counter = 1
            while Student.query.filter_by(email=student_email, school_id=current_user.school_id).first():
                student_email = f"{base_email}{counter}@{school_domain}"
                counter += 1
            
            # Generate password for student
            temp_password = secrets.token_urlsafe(8)
            
            # Create student record
            student = Student(
                student_id=student_id,
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                date_of_birth=form.date_of_birth.data,
                gender=form.gender.data,
                address=form.address.data,
                father_name=form.father_name.data,
                mother_name=form.mother_name.data,
                phone=form.phone.data,
                email=student_email,
                parent_email=form.parent_email.data,
                school_id=current_user.school_id
            )
            db.session.add(student)
            db.session.flush()  # Get student ID
            
            # Create user account for student
            user = User(
                email=student_email,
                full_name=f"{form.first_name.data} {form.last_name.data}",
                role='student',
                school_id=current_user.school_id,
                student_id=student.id,
                must_change_password=True
            )
            user.set_password(temp_password)
            db.session.add(user)
            db.session.flush()
            
            # Update student with user_id
            student.user_id = user.id
            
            # Automatically enroll student in selected class
            selected_class = Class.query.get(form.class_id.data)
            
            if not selected_class:
                flash('Selected class not found.', 'danger')
                db.session.rollback()
                return render_template('admin_create_student.html', form=form, context=context, classes=classes)
            
            # Check class capacity
            enrolled_count = StudentEnrollment.query.filter_by(
                class_id=selected_class.id,
                session_id=context['current_session'].id,
                is_active=True
            ).count()
            
            if enrolled_count >= selected_class.capacity:
                flash(f'Class {selected_class.name} is at full capacity ({selected_class.capacity} students).', 'danger')
                db.session.rollback()
                return render_template('admin_create_student.html', form=form, context=context, classes=classes)
            
            # Get next available roll number
            max_roll = db.session.query(db.func.max(StudentEnrollment.roll_number)).filter_by(
                class_id=selected_class.id,
                session_id=context['current_session'].id
            ).scalar() or 0
            
            enrollment = StudentEnrollment(
                student_id=student.id,
                class_id=form.class_id.data,
                session_id=context['current_session'].id,
                roll_number=max_roll + 1
            )
            db.session.add(enrollment)
            
            db.session.commit()
            
            flash(f'Student created successfully! Student ID: {student_id}, Login Email: {student_email}, Temporary Password: {temp_password}, Enrolled in: {selected_class.name}, Roll Number: {max_roll + 1}', 'success')
            return redirect(url_for('manage_students'))
            
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'Error creating student: {str(e)}')
            flash(f'Error creating student: {str(e)}', 'danger')
    
    return render_template('admin_create_student.html', form=form, context=context, classes=classes)

@app.route('/admin/students')
@role_required(['admin'])
def manage_students():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get search parameters
    search = request.args.get('search', '').strip()
    parent_email = request.args.get('parent_email', '').strip()
    class_id = request.args.get('class_id', type=int)
    status_filter = request.args.get('status', 'all')
    
    # Base query
    query = Student.query.filter_by(
        school_id=current_user.school_id,
        is_active=True
    )
    
    # Apply search filter (multiple fields)
    if search:
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Student.first_name.ilike(f'%{search}%'),
                Student.last_name.ilike(f'%{search}%'),
                Student.student_id.ilike(f'%{search}%'),
                Student.email.ilike(f'%{search}%'),
                Student.parent_email.ilike(f'%{search}%'),
                Student.father_name.ilike(f'%{search}%'),
                Student.mother_name.ilike(f'%{search}%')
            )
        )
    
    # Apply parent_email filter
    if parent_email:
        query = query.filter(Student.parent_email.ilike(f'%{parent_email}%'))
    
    students = query.order_by(Student.created_at.desc()).all()
    
    # Count siblings
    from collections import defaultdict
    parent_email_counts = defaultdict(int)
    all_students = Student.query.filter_by(
        school_id=current_user.school_id,
        is_active=True
    ).all()
    for s in all_students:
        if s.parent_email:
            parent_email_counts[s.parent_email] += 1
    
    # Get classes for dropdown
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=context['current_session'].id,
        is_active=True
    ).all()
    
    student_data = []
    enrolled_count = not_enrolled_count = 0
    
    for student in students:
        enrollment = StudentEnrollment.query.filter_by(
            student_id=student.id,
            session_id=context['current_session'].id,
            is_active=True
        ).first()
        
        enrolled = enrollment is not None
        siblings_count = parent_email_counts.get(student.parent_email, 0) if student.parent_email else 0
        
        # Apply class filter
        if class_id and enrollment and enrollment.class_id != class_id:
            continue
        
        # Apply status filter
        if status_filter == 'enrolled' and not enrolled:
            continue
        elif status_filter == 'not_enrolled' and enrolled:
            continue
        
        if enrolled:
            enrolled_count += 1
        else:
            not_enrolled_count += 1
        
        student_data.append({
            'student': student,
            'enrolled': enrolled,
            'class_name': enrollment.class_.name if enrollment else None,
            'class_id': enrollment.class_.id if enrollment else None,
            'roll_number': enrollment.roll_number if enrollment else None,
            'siblings_count': siblings_count
        })
    
    unique_parents = len(set([s.parent_email for s in students if s.parent_email]))
    
    return render_template('admin_manage_students.html',
                         student_data=student_data,
                         context=context,
                         search=search,
                         parent_email=parent_email,
                         selected_class=class_id,
                         status_filter=status_filter,
                         classes=classes,
                         unique_parents=unique_parents,
                         enrolled_count=enrolled_count,
                         not_enrolled_count=not_enrolled_count)

# Add this route in the app.py file
@app.route('/admin/enroll-student', methods=['GET', 'POST'])
@role_required(['admin'])
def enroll_student():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = EnrollStudentForm()
    context = get_school_context()
    
    if not context.get('current_session'):
        flash('No active session', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Populate form choices
    form.student_id.choices = [(s.id, f"{s.student_id} - {s.first_name} {s.last_name}") 
                              for s in Student.query.filter_by(
                                  school_id=current_user.school_id,
                                  is_active=True
                              ).all()]
    
    form.class_id.choices = [(c.id, f"{c.name} ({c.code})") 
                            for c in Class.query.filter_by(
                                school_id=current_user.school_id,
                                session_id=context['current_session'].id,
                                is_active=True
                            ).all()]
    
    # Get classes for the availability table
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=context['current_session'].id,
        is_active=True
    ).all()
    
    if form.validate_on_submit():
        try:
            # Check if student is already enrolled in this session
            existing = StudentEnrollment.query.filter_by(
                student_id=form.student_id.data,
                session_id=context['current_session'].id,
                is_active=True
            ).first()
            
            if existing:
                flash('Student is already enrolled in this session', 'danger')
            else:
                # Check if roll number already exists in this class
                roll_exists = StudentEnrollment.query.filter_by(
                    class_id=form.class_id.data,
                    session_id=context['current_session'].id,
                    roll_number=form.roll_number.data,
                    is_active=True
                ).first()
                
                if roll_exists:
                    flash('This roll number is already taken in this class', 'danger')
                else:
                    enrollment = StudentEnrollment(
                        student_id=form.student_id.data,
                        class_id=form.class_id.data,
                        session_id=context['current_session'].id,
                        roll_number=form.roll_number.data
                    )
                    db.session.add(enrollment)
                    db.session.commit()
                    
                    flash('Student enrolled successfully!', 'success')
                    return redirect(url_for('manage_students'))
                    
        except Exception as e:
            db.session.rollback()
            flash(f'Error enrolling student: {str(e)}', 'danger')
    
    return render_template('admin_enroll_student.html', form=form, context=context, classes=classes)

@app.route('/admin/assign-teacher', methods=['GET', 'POST'])
@role_required(['admin'])
def assign_teacher():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    form = AssignTeacherForm()
    context = get_school_context()
    
    if not context.get('current_session'):
        flash('No active session', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    # Populate form choices
    form.teacher_id.choices = [(t.id, t.full_name) 
                              for t in User.query.filter_by(
                                  school_id=current_user.school_id,
                                  role='teacher',
                                  is_active=True
                              ).all()]
    
    form.class_id.choices = [(c.id, f"{c.name} ({c.code})") 
                            for c in Class.query.filter_by(
                                school_id=current_user.school_id,
                                session_id=context['current_session'].id,
                                is_active=True
                            ).all()]
    
    if form.validate_on_submit():
        try:
            # Check if teacher is already assigned to this class for same subject
            existing = TeacherAssignment.query.filter_by(
                teacher_id=form.teacher_id.data,
                class_id=form.class_id.data,
                session_id=context['current_session'].id,
                subject=form.subject.data
            ).first()
            
            if existing:
                flash('Teacher is already assigned to this class for this subject', 'danger')
            else:
                # If setting as class teacher, remove existing class teacher
                if form.is_class_teacher.data:
                    TeacherAssignment.query.filter_by(
                        class_id=form.class_id.data,
                        session_id=context['current_session'].id,
                        is_class_teacher=True
                    ).update({'is_class_teacher': False})
                
                assignment = TeacherAssignment(
                    teacher_id=form.teacher_id.data,
                    class_id=form.class_id.data,
                    session_id=context['current_session'].id,
                    subject=form.subject.data,
                    is_class_teacher=form.is_class_teacher.data
                )
                db.session.add(assignment)
                db.session.commit()
                
                flash('Teacher assigned successfully!', 'success')
                return redirect(url_for('manage_teachers'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error assigning teacher: {str(e)}', 'danger')
    
    return render_template('admin_assign_teacher.html', form=form, context=context)

# ==================== TEACHER ROUTES ====================

@app.route('/teacher/dashboard')
@role_required(['teacher'])
def teacher_dashboard():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    # Check if school is suspended (as before)
    if current_user.school and not current_user.school.is_active:
        flash('This school has been suspended. Please contact the system administrator.', 'danger')
        return redirect(url_for('logout'))
    
    context = get_school_context()
    if not context.get('current_session'):
        flash('No active session', 'warning')
        return redirect(url_for('logout'))
    
    # Get teacher's assignments for current session
    assignments = TeacherAssignment.query.filter_by(
        teacher_id=current_user.id,
        session_id=context['current_session'].id
    ).all()
    
    assigned_classes = []
    total_students = 0
    today_attendance_list = Attendance.query.filter(
        Attendance.date == date.today()
    ).all()
    
    for assignment in assignments:
        class_obj = Class.query.get(assignment.class_id)
        if not class_obj:
            continue
        
        # Number of students enrolled
        student_count = StudentEnrollment.query.filter_by(
            class_id=class_obj.id,
            session_id=context['current_session'].id,
            is_active=True
        ).count()
        total_students += student_count
        
        # Check if attendance taken today
        attendance_taken = any(
            att.class_id == class_obj.id for att in today_attendance_list
        )
        
        # --- NEW: Get attendance statistics for this class ---
        stats = get_attendance_stats(
            class_obj.id,
            context['current_session'].id,
            'month'   # can also be 'week' or 'year'
        )
        
        assigned_classes.append({
            'class': class_obj,
            'assignment': assignment,
            'subject': assignment.subject,
            'is_class_teacher': assignment.is_class_teacher,
            'student_count': student_count,
            'attendance_taken': attendance_taken,
            'stats': stats   # <-- add the stats dictionary
        })
    
    return render_template('teacher_dashboard.html',
                         context=context,
                         assigned_classes=assigned_classes,
                         total_students=total_students,
                         today_attendance_list=today_attendance_list)

@app.route('/teacher/profile', methods=['GET', 'POST'])
@role_required(['teacher'])
def teacher_profile():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    if request.method == 'POST':
        try:
            current_user.full_name = request.form.get('full_name', current_user.full_name)
            current_user.phone = request.form.get('phone', current_user.phone)
            db.session.commit()
            flash('Profile updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {str(e)}', 'danger')
    
    return render_template('teacher_profile.html', context=context)

@app.route('/teacher/class/<int:class_id>')
@role_required(['teacher'])
def view_class(class_id):
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Verify teacher has access to this class
    assignment = TeacherAssignment.query.filter_by(
        teacher_id=current_user.id,
        class_id=class_id,
        session_id=context['current_session'].id
    ).first_or_404()
    
    class_obj = Class.query.get_or_404(class_id)
    students = StudentEnrollment.query.filter_by(
        class_id=class_id,
        session_id=context['current_session'].id,
        is_active=True
    ).order_by(StudentEnrollment.roll_number).all()
    
    return render_template('teacher_view_class.html',
                         context=context,
                         class_obj=class_obj,
                         students=students,
                         subject=assignment.subject,
                         is_class_teacher=assignment.is_class_teacher)

# ==================== API ENDPOINTS ====================

@app.route('/api/session-data/<int:session_id>')
@login_required
def get_session_data(session_id):
    """Get data for a specific session (for viewing historical data)"""
    if current_user.must_change_password:
        return jsonify({'error': 'Password change required'}), 403
    
    session_obj = AcademicSession.query.filter_by(
        id=session_id,
        school_id=current_user.school_id
    ).first_or_404()
    
    # Get data for this session
    data = {
        'session': {
            'id': session_obj.id,
            'name': session_obj.name,
            'start_date': session_obj.start_date.isoformat(),
            'end_date': session_obj.end_date.isoformat()
        },
        'classes': [],
        'teachers': [],
        'students': []
    }
    
    # Get classes
    classes = Class.query.filter_by(
        school_id=current_user.school_id,
        session_id=session_id,
        is_active=True
    ).all()
    
    for class_obj in classes:
        class_data = {
            'id': class_obj.id,
            'name': class_obj.name,
            'code': class_obj.code,
            'room_number': class_obj.room_number,
            'student_count': StudentEnrollment.query.filter_by(
                class_id=class_obj.id,
                session_id=session_id,
                is_active=True
            ).count()
        }
        data['classes'].append(class_data)
    
    return jsonify(data)

@app.route('/api/student/<int:student_id>/history')
@login_required
def get_student_history(student_id):
    """Get complete history of a student across all sessions"""
    if current_user.must_change_password:
        return jsonify({'error': 'Password change required'}), 403
    
    student = Student.query.filter_by(
        id=student_id,
        school_id=current_user.school_id
    ).first_or_404()
    
    enrollments = StudentEnrollment.query.filter_by(
        student_id=student_id
    ).order_by(StudentEnrollment.session_id.desc()).all()
    
    history = []
    for enrollment in enrollments:
        session_obj = AcademicSession.query.get(enrollment.session_id)
        class_obj = Class.query.get(enrollment.class_id)
        
        history.append({
            'session': session_obj.name,
            'session_id': session_obj.id,
            'class': class_obj.name,
            'class_code': class_obj.code,
            'roll_number': enrollment.roll_number,
            'enrollment_date': enrollment.enrollment_date.isoformat()
        })
    
    return jsonify({
        'student': {
            'id': student.id,
            'student_id': student.student_id,
            'name': f"{student.first_name} {student.last_name}"
        },
        'history': history
    })

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', 
                         error_code=404,
                         message='Page not found'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('error.html',
                         error_code=500,
                         message='Internal server error'), 500

@app.errorhandler(403)
def forbidden_error(error):
    return render_template('error.html',
                         error_code=403,
                         message='Access forbidden'), 403

# ==================== NEW SCHOOL DELETE/DEACTIVATE ROUTES ====================

@app.route('/developer/schools/<int:school_id>/delete', methods=['POST'])
@role_required(['developer'])
def delete_school(school_id):
    """Delete a school and all associated data"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    try:
        school = School.query.get_or_404(school_id)
        
        # Get all associated data
        users = User.query.filter_by(school_id=school_id).all()
        sessions = AcademicSession.query.filter_by(school_id=school_id).all()
        classes = Class.query.filter_by(school_id=school_id).all()
        students = Student.query.filter_by(school_id=school_id).all()
        
        # Delete all related data
        for user in users:
            # Delete teacher assignments first
            TeacherAssignment.query.filter_by(teacher_id=user.id).delete()
            db.session.delete(user)
        
        for session in sessions:
            StudentEnrollment.query.filter_by(session_id=session.id).delete()
            db.session.delete(session)
        
        for class_obj in classes:
            StudentEnrollment.query.filter_by(class_id=class_obj.id).delete()
            TeacherAssignment.query.filter_by(class_id=class_obj.id).delete()
            db.session.delete(class_obj)
        
        for student in students:
            StudentEnrollment.query.filter_by(student_id=student.id).delete()
            db.session.delete(student)
        
        # Finally delete the school
        db.session.delete(school)
        db.session.commit()
        
        flash(f'School "{school.name}" has been permanently deleted along with all associated data.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting school: {str(e)}', 'danger')
    
    return redirect(url_for('manage_schools'))

@app.route('/developer/schools/<int:school_id>/suspend', methods=['POST'])
@role_required(['developer'])
def suspend_school(school_id):
    """Suspend school services (soft delete - keeps data but prevents access)"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    try:
        school = School.query.get_or_404(school_id)
        
        # Suspend the school
        school.is_active = False
        
        # Also suspend all associated users
        users = User.query.filter_by(school_id=school_id).all()
        for user in users:
            user.is_active = False
        
        db.session.commit()
        
        flash(f'School "{school.name}" services have been suspended. Admin and teachers cannot login.', 'warning')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error suspending school: {str(e)}', 'danger')
    
    return redirect(url_for('manage_schools'))

@app.route('/developer/schools/<int:school_id>/reactivate', methods=['POST'])
@role_required(['developer'])
def reactivate_school(school_id):
    """Reactivate a suspended school"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    try:
        school = School.query.get_or_404(school_id)
        
        # Reactivate the school
        school.is_active = True
        
        # Also reactivate all associated users
        users = User.query.filter_by(school_id=school_id).all()
        for user in users:
            user.is_active = True
        
        db.session.commit()
        
        flash(f'School "{school.name}" has been reactivated. Admin and teachers can now login.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error reactivating school: {str(e)}', 'danger')
    
    return redirect(url_for('manage_schools'))

@app.route('/developer/schools/<int:school_id>/details')
@role_required(['developer'])
def school_details(school_id):
    """View school details with statistics"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    school = School.query.get_or_404(school_id)
    
    # Get statistics
    stats = {
        'total_admins': User.query.filter_by(school_id=school_id, role='admin', is_active=True).count(),
        'total_teachers': User.query.filter_by(school_id=school_id, role='teacher', is_active=True).count(),
        'total_students': Student.query.filter_by(school_id=school_id, is_active=True).count(),
        'total_classes': Class.query.filter_by(school_id=school_id, is_active=True).count(),
        'total_sessions': AcademicSession.query.filter_by(school_id=school_id, is_active=True).count(),
        'active_sessions': AcademicSession.query.filter_by(school_id=school_id, is_active=True, is_current=True).count()
    }
    
    # Get recent activity
    recent_students = Student.query.filter_by(school_id=school_id).order_by(Student.created_at.desc()).limit(5).all()
    recent_admins = User.query.filter_by(school_id=school_id, role='admin').order_by(User.created_at.desc()).limit(3).all()
    
    return render_template('developer_school_details.html',
                         school=school,
                         stats=stats,
                         recent_students=recent_students,
                         recent_admins=recent_admins)

# ==================== INITIALIZATION ====================

def create_tables():
    """Create database tables if they don't exist"""
    with app.app_context():
        try:
            # First, check if student_id column exists
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            
            # Create all tables first
            db.create_all()
            
            # Check if student_id column needs to be added
            columns = [col['name'] for col in inspector.get_columns('users')]
            if 'student_id' not in columns:
                print("Adding student_id column to users table...")
                # Add the column manually
                db.engine.execute(text('ALTER TABLE users ADD COLUMN student_id INTEGER REFERENCES students(id)'))
                print("Column added successfully!")
            
            # Create developer account if it doesn't exist
            developer = User.query.filter_by(role='developer').first()
            if not developer:
                developer = User(
                    email='developer@schoolerp.com',
                    full_name='System Developer',
                    role='developer',
                    must_change_password=False
                )
                developer.set_password('developer123')  # Change this in production!
                db.session.add(developer)
                db.session.commit()
                print("Developer account created. Email: developer@schoolerp.com, Password: developer123")
                
        except Exception as e:
            print(f"Error creating tables: {e}")
            db.session.rollback()

def setup_logging():
    """Setup application logging"""
    if not os.path.exists('logs'):
        os.mkdir('logs')
    
    file_handler = RotatingFileHandler('logs/school_erp.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('School ERP startup')


# ==================== PASSWORD RESET BY DEVELOPER ====================

@app.route('/developer/reset-password/<int:user_id>', methods=['GET', 'POST'])
@role_required(['developer'])
def developer_reset_password(user_id):
    """Developer can reset password for any user"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    user = User.query.get_or_404(user_id)
    
    # Check if trying to reset developer password (only for non-developer users)
    if user.role == 'developer' and user.id != current_user.id:
        flash('Cannot reset password for another developer', 'danger')
        return redirect(request.referrer or url_for('developer_dashboard'))
    
    form = DeveloperResetPasswordForm()
    
    if form.validate_on_submit():
        try:
            # Get form data
            reason = form.reason.data or 'No reason provided'
            force_logout = form.force_logout.data
            notify_user = form.notify_user.data
            
            # Generate a new random password
            new_password = secrets.token_urlsafe(8)
            user.set_password(new_password)
            user.must_change_password = True  # Force user to change on next login
            
            # Log the reset action
            app.logger.info(f'Developer {current_user.email} reset password for user {user.email}. Reason: {reason}')
            
            db.session.commit()
            
            # Show success message with new password
            flash(f'Password reset successful for {user.full_name}! New temporary password: {new_password}', 'success')
            
            # If notify_user is checked, show additional message
            if notify_user:
                flash(f'Email notification would be sent to {user.email} in production.', 'info')
            
            return redirect(url_for('school_details', school_id=user.school_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error resetting password: {str(e)}', 'danger')
    
    return render_template('developer_reset_password.html', user=user, form=form)

@app.route('/developer/schools/<int:school_id>/reset-admin-password', methods=['POST'])
@role_required(['developer'])
def reset_admin_password(school_id):
    """Quick reset admin password (generates random password)"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    try:
        # Get the school
        school = School.query.get_or_404(school_id)
        
        # Get the first admin for this school
        admin = User.query.filter_by(
            school_id=school_id, 
            role='admin',
            is_active=True
        ).first()
        
        if not admin:
            flash('No active admin found for this school', 'danger')
            return redirect(url_for('school_details', school_id=school_id))
        
        # Generate new password
        new_password = secrets.token_urlsafe(8)
        admin.set_password(new_password)
        admin.must_change_password = True
        
        db.session.commit()
        
        flash(f'Admin password reset successful! New temporary password for {admin.full_name}: {new_password}', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error resetting admin password: {str(e)}', 'danger')
    
    return redirect(url_for('school_details', school_id=school_id))

# ==================== FORGOT PASSWORD FUNCTIONALITY ====================

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Forgot password functionality for all users"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = ForgotPasswordForm()
    
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data, is_active=True).first()
        
        if user:
            # Check if user's school is active (for non-developer users)
            if user.role != 'developer' and user.school_id:
                school = School.query.get(user.school_id)
                if not school or not school.is_active:
                    flash('This school has been suspended. Please contact the system administrator.', 'danger')
                    return redirect(url_for('login'))
            
            # Generate a password reset token
            reset_token = secrets.token_urlsafe(32)
            
            # In a real app, you would:
            # 1. Save the reset token in the database with expiry
            # 2. Send email with reset link
            # 3. Here we'll just show the token for demo purposes
            
            flash(f'Password reset link has been sent to {form.email.data}. For demo purposes, contact system administrator.', 'info')
        else:
            flash('No account found with that email address', 'danger')
    
    return render_template('auth_forgot_password.html', form=form)


# ==================== USER ACTIVATION/DEACTIVATION ROUTES ====================

@app.route('/developer/user/<int:user_id>/deactivate', methods=['POST'])
@role_required(['developer'])
def deactivate_user(user_id):
    """Deactivate a user account"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    try:
        user = User.query.get_or_404(user_id)
        
        # Cannot deactivate self or other developers
        if user.id == current_user.id:
            flash('Cannot deactivate your own account', 'danger')
        elif user.role == 'developer':
            flash('Cannot deactivate other developer accounts', 'danger')
        else:
            user.is_active = False
            db.session.commit()
            flash(f'User {user.full_name} has been deactivated', 'success')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error deactivating user: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('developer_dashboard'))

@app.route('/developer/user/<int:user_id>/activate', methods=['POST'])
@role_required(['developer'])
def activate_user(user_id):
    """Activate a user account"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    try:
        user = User.query.get_or_404(user_id)
        
        # Check if user's school is active
        if user.school_id:
            school = School.query.get(user.school_id)
            if not school.is_active:
                flash(f'Cannot activate user because school {school.name} is suspended', 'danger')
                return redirect(request.referrer or url_for('developer_dashboard'))
        
        user.is_active = True
        db.session.commit()
        flash(f'User {user.full_name} has been activated', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error activating user: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('developer_dashboard'))


@app.route('/admin/students/siblings/<parent_email>')
@role_required(['admin'])
def view_siblings(parent_email):
    """View all siblings with same parent email"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Find all students with same parent email in this school
    siblings = Student.query.filter_by(
        school_id=current_user.school_id,
        parent_email=parent_email,
        is_active=True
    ).order_by(Student.date_of_birth).all()
    
    # Get their enrollment info
    sibling_data = []
    for sibling in siblings:
        enrollment = StudentEnrollment.query.filter_by(
            student_id=sibling.id,
            session_id=context['current_session'].id,
            is_active=True
        ).first()
        
        sibling_data.append({
            'student': sibling,
            'enrollment': enrollment
        })
    
    return render_template('admin_view_siblings.html',
                         sibling_data=sibling_data,
                         parent_email=parent_email,
                         context=context)


@app.route('/admin/teachers/<int:teacher_id>/reset-password', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def reset_teacher_password(teacher_id):
    """Admin resets teacher password"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get teacher (must be in same school)
    teacher = User.query.filter_by(
        id=teacher_id,
        school_id=current_user.school_id,
        role='teacher'
    ).first_or_404()
    
    form = ResetTeacherPasswordForm()
    
    if form.validate_on_submit():
        try:
            # Generate new password
            if form.generate_temporary.data:
                new_password = secrets.token_urlsafe(8)
            else:
                # Allow admin to set custom password
                new_password = request.form.get('custom_password')
                if not new_password or len(new_password) < 6:
                    flash('Custom password must be at least 6 characters', 'danger')
                    return render_template('admin_reset_teacher_password.html', 
                                         form=form, teacher=teacher, context=context)
            
            # Update teacher password
            teacher.set_password(new_password)
            teacher.must_change_password = True
            
            # Log the action
            from datetime import datetime
            activity_log = {
                'action': 'password_reset',
                'admin_id': current_user.id,
                'teacher_id': teacher.id,
                'reason': form.reason.data,
                'timestamp': datetime.utcnow().isoformat(),
                'ip_address': request.remote_addr
            }
            
            # Store log in session (in production, save to database)
            if 'admin_actions' not in session:
                session['admin_actions'] = []
            session['admin_actions'].append(activity_log)
            
            db.session.commit()
            
            # Show success message with password
            if form.generate_temporary.data:
                flash_message = f'Password reset successful for {teacher.full_name}! Temporary password: {new_password}'
            else:
                flash_message = f'Password updated successfully for {teacher.full_name}!'
            
            flash(flash_message, 'success')
            
            # Email notification (simulated)
            if form.notify_via_email.data:
                flash(f'Email notification would be sent to {teacher.email} in production.', 'info')
            
            return redirect(url_for('manage_teachers'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error resetting password: {str(e)}', 'danger')
    
    return render_template('admin_reset_teacher_password.html', 
                         form=form, teacher=teacher, context=context)


@app.route('/admin/teachers/<int:teacher_id>/edit', methods=['GET', 'POST'])
@role_required(['admin'])
@school_active_required
def edit_teacher(teacher_id):
    """Admin edits teacher details"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get teacher (must be in same school)
    teacher = User.query.filter_by(
        id=teacher_id,
        school_id=current_user.school_id,
        role='teacher'
    ).first_or_404()
    
    form = EditTeacherForm()
    
    if request.method == 'GET':
        # Pre-populate form with existing data
        form.full_name.data = teacher.full_name
        form.email.data = teacher.email
        form.phone.data = teacher.phone
        form.status.data = 'active' if teacher.is_active else 'inactive'
        
        # Get teacher's primary subjects from assignments
        assignments = TeacherAssignment.query.filter_by(teacher_id=teacher_id).all()
        subjects = list(set([a.subject for a in assignments]))
        form.subjects.data = ', '.join(subjects)
    
    if form.validate_on_submit():
        try:
            # Check if email is being changed and if it's already taken by another user
            if form.email.data != teacher.email:
                existing_user = User.query.filter(
                    User.email == form.email.data,
                    User.id != teacher.id,
                    User.school_id == current_user.school_id
                ).first()
                if existing_user:
                    flash('Email already exists for another user in this school', 'danger')
                    return render_template('admin_edit_teacher.html', 
                                         form=form, teacher=teacher, context=context)
            
            # Update teacher details
            teacher.full_name = form.full_name.data
            teacher.email = form.email.data
            teacher.phone = form.phone.data
            teacher.is_active = (form.status.data == 'active')
            
            # Log the action
            activity_log = {
                'action': 'teacher_edit',
                'admin_id': current_user.id,
                'teacher_id': teacher.id,
                'changes': {
                    'old_email': teacher.email,
                    'new_email': form.email.data,
                    'old_name': teacher.full_name,
                    'new_name': form.full_name.data
                },
                'timestamp': datetime.utcnow().isoformat(),
                'ip_address': request.remote_addr
            }
            
            if 'admin_actions' not in session:
                session['admin_actions'] = []
            session['admin_actions'].append(activity_log)
            
            db.session.commit()
            
            flash(f'Teacher {teacher.full_name} updated successfully!', 'success')
            return redirect(url_for('manage_teachers'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating teacher: {str(e)}', 'danger')
    
    return render_template('admin_edit_teacher.html', 
                         form=form, teacher=teacher, context=context)

@app.route('/admin/timetable/export/<int:class_id>/pdf')
@role_required(['admin', 'teacher'])
def export_timetable_pdf(class_id):
    """Export timetable as PDF"""
    # Use WeasyPrint or ReportLab to generate PDF
    # For now, redirect to view with print layout
    return redirect(url_for('view_timetable', class_id=class_id, print=true))

@app.route('/admin/timetable/reorder', methods=['POST'])
@role_required(['admin'])
def reorder_timetable():
    """Reorder periods via drag and drop"""
    data = request.get_json()
    timetable_id = data.get('timetable_id')
    periods = data.get('periods', [])
    
    try:
        for period_data in periods:
            entry = TimetableEntry.query.get(period_data['id'])
            if entry:
                entry.period = period_data['period']
                entry.day = period_data['day']
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/admin/teachers/<int:teacher_id>/view', methods=['GET'])
@role_required(['admin'])
@school_active_required
def view_teacher_details(teacher_id):
    """View complete teacher details"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    
    # Get teacher (must be in same school)
    teacher = User.query.filter_by(
        id=teacher_id,
        school_id=current_user.school_id,
        role='teacher'
    ).first_or_404()
    
    # Get current session assignments
    current_assignments = TeacherAssignment.query.filter_by(
        teacher_id=teacher_id,
        session_id=context['current_session'].id
    ).all()
    
    # Get all assignments (historical)
    all_assignments = TeacherAssignment.query.filter_by(
        teacher_id=teacher_id
    ).order_by(TeacherAssignment.session_id.desc()).all()
    
    # Organize assignments by session
    assignments_by_session = {}
    for assignment in all_assignments:
        session_id = assignment.session_id
        if session_id not in assignments_by_session:
            assignments_by_session[session_id] = []
        assignments_by_session[session_id].append(assignment)
    
    # Get session details
    sessions_data = []
    for session_id, assignments in assignments_by_session.items():
        session = AcademicSession.query.get(session_id)
        sessions_data.append({
            'session': session,
            'assignments': assignments
        })
    
    # Sort sessions by date (most recent first)
    sessions_data.sort(key=lambda x: x['session'].start_date, reverse=True)
    
    return render_template('admin_view_teacher_details.html',
                         teacher=teacher,
                         context=context,
                         current_assignments=current_assignments,
                         sessions_data=sessions_data)

@app.route('/admin/create-test-fee-data')
@role_required(['admin'])
def create_test_fee_data():
    """Create test fee data for debugging"""
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    
    context = get_school_context()
    school_id = current_user.school_id
    
    # Check if there's an active session
    if not context.get('current_session'):
        flash('No active session found. Please create a session first.', 'warning')
        return redirect(url_for('create_session'))
    
    session_id = context['current_session'].id
    
    try:
        # Create a test fee structure if it doesn't exist
        fee_structure = FeeStructure.query.filter_by(
            school_id=school_id,
            session_id=session_id,
            name="Test Tuition Fee"
        ).first()
        
        if not fee_structure:
            fee_structure = FeeStructure(
                name="Test Tuition Fee",
                description="Test fee for debugging",
                amount=5000.0,
                frequency='monthly',
                is_active=True,
                school_id=school_id,
                session_id=session_id,
                class_id=None  # For all classes
            )
            db.session.add(fee_structure)
            db.session.commit()
            fee_structure_id = fee_structure.id
        else:
            fee_structure_id = fee_structure.id
        
        # Get first 5 students
        students = Student.query.filter_by(school_id=school_id, is_active=True).limit(5).all()
        
        assigned_count = 0
        for student in students:
            # Check if fee already assigned
            existing_fee = StudentFee.query.filter_by(
                student_id=student.id,
                fee_structure_id=fee_structure_id,
                session_id=session_id
            ).first()
            
            if not existing_fee:
                # Create student fee record
                student_fee = StudentFee(
                    student_id=student.id,
                    fee_structure_id=fee_structure_id,
                    session_id=session_id,
                    fee_amount=5000.0,
                    discount_amount=500.0,
                    fine_amount=100.0,
                    paid_amount=2000.0,
                    due_date=date.today() + timedelta(days=30),
                    status='partial'
                )
                db.session.add(student_fee)
                assigned_count += 1
        
        db.session.commit()
        
        flash(f'Test fee data created successfully! Assigned fees to {assigned_count} students.', 'success')
        return redirect(url_for('admin_dashboard'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating test data: {str(e)}', 'danger')
        return redirect(url_for('admin_dashboard'))

def log_admin_action(action_type, target_id, details):
    """Log admin actions for security audit"""
    from datetime import datetime
    import json
    
    log_entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'admin_id': current_user.id,
        'admin_email': current_user.email,
        'action': action_type,
        'target_id': target_id,
        'details': details,
        'ip_address': request.remote_addr,
        'user_agent': request.user_agent.string
    }
    
    # In production, save to database or log file
    # For now, we'll print to console and store in session
    app.logger.info(f'ADMIN ACTION: {json.dumps(log_entry)}')
    
    # Store in session for immediate access
    if 'audit_log' not in session:
        session['audit_log'] = []
    
    # Keep only last 50 actions
    session['audit_log'].append(log_entry)
    if len(session['audit_log']) > 50:
        session['audit_log'] = session['audit_log'][-50:]
# Add the ForgotPasswordForm class
class ForgotPasswordForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Reset Password')

# ==================== MAIN APPLICATION ====================
setup_logging()
with app.app_context():
    create_tables()
if __name__ == '__main__':
    app.run(debug=True, port=5000)











