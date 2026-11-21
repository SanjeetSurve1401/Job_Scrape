import os
import re
import json
import time
from datetime import datetime
import requests
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from src.tailor_cv.pdf_parser import extract_text_from_pdf
from src.tailor_cv.claude_client import ClaudeClient, accumulate_job_tokens, get_llm_client

def sanitize_filename(name: str) -> str:
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_').lower()

def get_tailored_cv_data(client, cv_text, job_details) -> dict:
    if hasattr(client, 'get_tailored_cv_data'):
        res = client.get_tailored_cv_data(cv_text, job_details)
        client.last_usage = res.get("usage")
        return res.get("data")
    raise ValueError("Unsupported client type passed to get_tailored_cv_data")

def get_tailored_cl_data(client, cv_text, job_details) -> dict:
    if hasattr(client, 'get_tailored_cl_data'):
        res = client.get_tailored_cl_data(cv_text, job_details)
        client.last_usage = res.get("usage")
        return res.get("data")
    raise ValueError("Unsupported client type passed to get_tailored_cl_data")

def get_tailored_ats_score(client, cv_data: dict, job_details: dict) -> str:
    if hasattr(client, 'get_tailored_ats_score'):
        res = client.get_tailored_ats_score(cv_data, job_details)
        client.last_usage = res.get("usage")
        return res.get("ats_score")
    raise ValueError("Unsupported client type passed to get_tailored_ats_score")

def make_pdf_section_header(title: str, width: float = 523.27) -> Table:
    """Creates a section header matching Overleaf: Blue uppercase text + thin black horizontal line."""
    p = Paragraph(f"<font color='#0044CC'><b>{title.upper()}</b></font>", ParagraphStyle(
        'SecHeader',
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=13,
    ))
    t = Table([[p]], colWidths=[width])
    t.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 0.75, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    return t

def generate_pdf_cv(cv_data: dict, output_path: str):
    # A4: 595.27 x 841.89 pt. 0.5 in margins (36 pt) -> Content width = 523.27 pt
    content_width = 523.27
    doc = SimpleDocTemplate(
        output_path, 
        pagesize=A4, 
        rightMargin=36, 
        leftMargin=36, 
        topMargin=36, 
        bottomMargin=36
    )
    story = []
    styles = getSampleStyleSheet()
    
    body_style = ParagraphStyle('CVBody', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11.5, textColor=colors.black)
    italic_body = ParagraphStyle('CVItalicBody', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=9, leading=11.5, textColor=colors.black)
    bullet_style = ParagraphStyle('CVBullet', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11.5, textColor=colors.black, leftIndent=12, firstLineIndent=-8, spaceAfter=1.5)
    right_style = ParagraphStyle('CVRight', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11.5, textColor=colors.black, alignment=2)
    right_italic = ParagraphStyle('CVRightItalic', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=9, leading=11.5, textColor=colors.black, alignment=2)
    
    # 1. Header (Two-column: Left = Name & LinkedIn, Right = Location & Email)
    contact = cv_data.get('contact_info', {})
    name_str = contact.get('name', 'Sanjeet Surve')
    linkedin_str = contact.get('linkedin', 'linkedin.com/in/sanjeetsurve')
    loc_str = contact.get('location', 'Mumbai, MH, India')
    email_str = contact.get('email', 'sanjeetsurveofficial@gmail.com')
    
    name_style = ParagraphStyle(
        'CVName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.black
    )
    header_sub_left = ParagraphStyle(
        'CVHeaderSubLeft',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.black
    )
    header_sub_right = ParagraphStyle(
        'CVHeaderSubRight',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.black,
        alignment=2
    )

    header_tbl = Table([
        [Paragraph(f"<b>{name_str}</b>", name_style), Paragraph(f"Location: {loc_str}", header_sub_right)],
        [Paragraph(f"LinkedIn: {linkedin_str}", header_sub_left), Paragraph(f"Email: {email_str}", header_sub_right)]
    ], colWidths=[330, 193.27])
    header_tbl.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 4))
    
    # 2. Professional Summary Section
    summary = cv_data.get('professional_summary')
    if summary:
        story.append(make_pdf_section_header("QUALITY ASSURANCE ENGINEER", content_width))
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"<i>{summary}</i>", italic_body))
        story.append(Spacer(1, 4))
        
    # 3. Technical Skills Section
    skills = cv_data.get('skills', {})
    if skills:
        story.append(make_pdf_section_header("TECHNICAL SKILLS", content_width))
        story.append(Spacer(1, 3))
        skills_table_data = []
        for skill_type, skill_list in skills.items():
            if skill_list:
                label = skill_type.replace('_', ' ').title()
                p_label = Paragraph(f"<b>{label}</b>", body_style)
                p_colon = Paragraph(":", body_style)
                p_vals = Paragraph(", ".join(skill_list), body_style)
                skills_table_data.append([p_label, p_colon, p_vals])
        if skills_table_data:
            sk_tbl = Table(skills_table_data, colWidths=[85, 12, 426.27])
            sk_tbl.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0.5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0.5),
            ]))
            story.append(sk_tbl)
        story.append(Spacer(1, 4))
        
    # 4. Experience Section
    experience = cv_data.get('work_experience', [])
    if experience:
        story.append(make_pdf_section_header("EXPERIENCE", content_width))
        story.append(Spacer(1, 3))
        for job in experience:
            comp_name = job.get('company', 'Company')
            job_loc = job.get('location', '')
            role_name = job.get('role', 'Role')
            dates_str = f"{job.get('start_date', '')} -- {job.get('end_date', 'Present')}"
            
            job_head_data = [
                [Paragraph(f"<b>{comp_name}</b>", body_style), Paragraph(job_loc, right_style)],
                [Paragraph(f"<i>{role_name}</i>", italic_body), Paragraph(f"<i>{dates_str}</i>", right_italic)]
            ]
            job_tbl = Table(job_head_data, colWidths=[350, 173.27])
            job_tbl.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0.5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0.5),
            ]))
            story.append(job_tbl)
            story.append(Spacer(1, 2))
            for ach in job.get('achievements', []):
                story.append(Paragraph(f"&bull; {ach}", bullet_style))
            story.append(Spacer(1, 3))
            
    # 5. Education Section
    education = cv_data.get('education', [])
    if not education:
        # Standard education entries from template
        education = [
            {"institution": "CDAC - Centre for Development of Advanced Computing", "location": "Bandra, MH, India", "degree": "Post Graduation Diploma", "graduation_year": "Aug 2024 -- May 2025"},
            {"institution": "MIT World Peace University, Pune", "location": "Pune, MH, India", "degree": "Bachelor of Technology in Electronics & Communication Engineering", "graduation_year": "Sep 2021 -- Jul 2024"}
        ]
    if education:
        story.append(make_pdf_section_header("EDUCATION", content_width))
        story.append(Spacer(1, 3))
        for edu in education:
            inst = edu.get('institution', '')
            e_loc = edu.get('location', '')
            deg = edu.get('degree', '')
            if edu.get('major'):
                deg += f" in {edu.get('major')}"
            e_dates = edu.get('graduation_year', '')
            
            edu_head_data = [
                [Paragraph(f"<b>{inst}</b>", body_style), Paragraph(e_loc, right_style)],
                [Paragraph(f"<i>{deg}</i>", italic_body), Paragraph(f"<i>{e_dates}</i>", right_italic)]
            ]
            edu_tbl = Table(edu_head_data, colWidths=[370, 153.27])
            edu_tbl.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0.5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0.5),
            ]))
            story.append(edu_tbl)
            story.append(Spacer(1, 2))
        story.append(Spacer(1, 2))
        
    # 6. Projects Section
    projects = cv_data.get('projects', [])
    if projects:
        story.append(make_pdf_section_header("PROJECTS", content_width))
        story.append(Spacer(1, 3))
        for proj in projects:
            title = proj.get('title', 'Project')
            tech = proj.get('technologies', '')
            p_head_data = [
                [Paragraph(f"<b>{title}</b>", body_style), Paragraph(f"<i>{tech}</i>", right_italic)]
            ]
            p_tbl = Table(p_head_data, colWidths=[330, 193.27])
            p_tbl.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0.5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0.5),
            ]))
            story.append(p_tbl)
            story.append(Spacer(1, 2))
            if proj.get('description'):
                story.append(Paragraph(f"&bull; {proj.get('description')}", bullet_style))
            for ach in proj.get('achievements', []):
                story.append(Paragraph(f"&bull; {ach}", bullet_style))
            story.append(Spacer(1, 3))
            
    # 7. Certifications & Publications
    certs = cv_data.get('certifications', [])
    if not certs:
        certs = [
            "Co-author of 'User Centric Sensor Array for Real-Time Air Pollutant Surveillance' -- IEEE Xplore (Apr 2024)",
            "Docker for the Absolute Beginner -- Hands On -- DevOps (Udemy, 2025)",
            "Advanced Software Engineering Job Simulation (Walmart Global, 2025)",
            "Full Stack Development Certification (upGrad, 2024)"
        ]
    if certs:
        story.append(make_pdf_section_header("CERTIFICATIONS & PUBLICATIONS", content_width))
        story.append(Spacer(1, 3))
        for cert in certs:
            story.append(Paragraph(f"&bull; {cert}", bullet_style))
            
    doc.build(story)

def generate_pdf_cover_letter(cl_data: dict, output_path: str):
    doc = SimpleDocTemplate(output_path, pagesize=A4, rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54)
    story = []
    styles = getSampleStyleSheet()
    
    body_style = ParagraphStyle('CLBody', parent=styles['Normal'], fontSize=11, leading=15, textColor=colors.HexColor('#2D3748'), spaceAfter=10)
    sender_style = ParagraphStyle('CLSender', parent=styles['Normal'], fontSize=11, leading=15, textColor=colors.HexColor('#1A365D'), spaceAfter=3)
    date_style = ParagraphStyle('CLDate', parent=styles['Normal'], fontSize=11, leading=15, textColor=colors.HexColor('#4A5568'), spaceAfter=12)
    recipient_style = ParagraphStyle('CLRecipient', parent=styles['Normal'], fontSize=11, leading=15, textColor=colors.HexColor('#2D3748'), spaceAfter=10)
    subject_style = ParagraphStyle('CLSubject', parent=styles['Normal'], fontSize=11, leading=15, fontName='Helvetica-Bold', textColor=colors.HexColor('#1A365D'), spaceAfter=12)

    current_date = cl_data.get('date') or datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(current_date, date_style))
    story.append(Paragraph(cl_data.get('recipient_name', 'Hiring Manager / Recruiter'), recipient_style))
    story.append(Paragraph(cl_data.get('company_name', 'Company Name'), recipient_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph(cl_data.get('subject', 'Application'), subject_style))
    story.append(Paragraph(cl_data.get('salutation', 'Dear Hiring Manager,'), body_style))
    story.append(Paragraph(cl_data.get('opening_paragraph', ''), body_style))
    for para in cl_data.get('body_paragraphs', []):
        story.append(Paragraph(para, body_style))
    story.append(Paragraph(cl_data.get('closing_paragraph', ''), body_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph(cl_data.get('sign_off', 'Sincerely,'), body_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>{cl_data.get('sender_name', 'Candidate Name')}</b>", sender_style))
    
    doc.build(story)

def generate_docx_cv(cv_data: dict, output_path: str):
    doc = docx.Document()
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)
        
    blue_color = RGBColor(0x00, 0x44, 0xCC)
    black_color = RGBColor(0x00, 0x00, 0x00)
    
    def add_section_heading(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text.upper())
        run.bold = True
        run.font.size = Pt(10.5)
        run.font.color.rgb = blue_color
        
        # Add thin horizontal rule below section heading
        p_hr = doc.add_paragraph()
        p_hr.paragraph_format.space_before = Pt(0)
        p_hr.paragraph_format.space_after = Pt(4)
        run_hr = p_hr.add_run("―" * 58)
        run_hr.font.size = Pt(8)
        run_hr.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    # 1. Header (Two-column: Left = Name & LinkedIn, Right = Location & Email)
    contact = cv_data.get('contact_info', {})
    name_str = contact.get('name', 'Sanjeet Surve')
    linkedin_str = contact.get('linkedin', 'linkedin.com/in/sanjeetsurve')
    loc_str = contact.get('location', 'Mumbai, MH, India')
    email_str = contact.get('email', 'sanjeetsurveofficial@gmail.com')
    
    tbl_hdr = doc.add_table(rows=1, cols=2)
    tbl_hdr.autofit = False
    tbl_hdr.columns[0].width = Inches(4.5)
    tbl_hdr.columns[1].width = Inches(3.0)
    
    cell_l = tbl_hdr.cell(0, 0)
    p_name = cell_l.paragraphs[0]
    p_name.paragraph_format.space_after = Pt(1)
    r_name = p_name.add_run(name_str)
    r_name.bold = True
    r_name.font.size = Pt(20)
    
    p_li = cell_l.add_paragraph()
    p_li.paragraph_format.space_after = Pt(0)
    r_li = p_li.add_run(f"LinkedIn: {linkedin_str}")
    r_li.font.size = Pt(9)
    
    cell_r = tbl_hdr.cell(0, 1)
    p_loc = cell_r.paragraphs[0]
    p_loc.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_loc.paragraph_format.space_after = Pt(1)
    r_loc = p_loc.add_run(f"Location: {loc_str}")
    r_loc.font.size = Pt(9)
    
    p_em = cell_r.add_paragraph()
    p_em.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_em.paragraph_format.space_after = Pt(0)
    r_em = p_em.add_run(f"Email: {email_str}")
    r_em.font.size = Pt(9)
    
    # 2. Professional Summary Section
    summary = cv_data.get('professional_summary')
    if summary:
        add_section_heading("QUALITY ASSURANCE ENGINEER")
        p_sum = doc.add_paragraph()
        p_sum.paragraph_format.space_after = Pt(4)
        r_sum = p_sum.add_run(summary)
        r_sum.italic = True
        r_sum.font.size = Pt(9)
        
    # 3. Technical Skills Section
    skills = cv_data.get('skills', {})
    if skills:
        add_section_heading("TECHNICAL SKILLS")
        for skill_type, skill_list in skills.items():
            if skill_list:
                label = skill_type.replace('_', ' ').title()
                p_sk = doc.add_paragraph()
                p_sk.paragraph_format.space_after = Pt(1.5)
                r_lbl = p_sk.add_run(f"{label:<15}:  ")
                r_lbl.bold = True
                r_lbl.font.size = Pt(9)
                r_val = p_sk.add_run(", ".join(skill_list))
                r_val.font.size = Pt(9)
                
    # 4. Experience Section
    experience = cv_data.get('work_experience', [])
    if experience:
        add_section_heading("EXPERIENCE")
        for job in experience:
            comp_name = job.get('company', 'Company')
            job_loc = job.get('location', '')
            role_name = job.get('role', 'Role')
            dates_str = f"{job.get('start_date', '')} -- {job.get('end_date', 'Present')}"
            
            tbl_job = doc.add_table(rows=2, cols=2)
            tbl_job.autofit = False
            tbl_job.columns[0].width = Inches(5.0)
            tbl_job.columns[1].width = Inches(2.5)
            
            p_c = tbl_job.cell(0, 0).paragraphs[0]
            p_c.paragraph_format.space_after = Pt(0)
            r_c = p_c.add_run(comp_name)
            r_c.bold = True
            r_c.font.size = Pt(9)
            
            p_l = tbl_job.cell(0, 1).paragraphs[0]
            p_l.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p_l.paragraph_format.space_after = Pt(0)
            r_l = p_l.add_run(job_loc)
            r_l.font.size = Pt(9)
            
            p_r = tbl_job.cell(1, 0).paragraphs[0]
            p_r.paragraph_format.space_after = Pt(0)
            r_r = p_r.add_run(role_name)
            r_r.italic = True
            r_r.font.size = Pt(9)
            
            p_d = tbl_job.cell(1, 1).paragraphs[0]
            p_d.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p_d.paragraph_format.space_after = Pt(0)
            r_d = p_d.add_run(dates_str)
            r_d.italic = True
            r_d.font.size = Pt(9)
            
            for ach in job.get('achievements', []):
                p_ach = doc.add_paragraph(style='List Bullet')
                p_ach.paragraph_format.space_after = Pt(1.5)
                p_ach.paragraph_format.left_indent = Inches(0.2)
                r_ach = p_ach.add_run(ach)
                r_ach.font.size = Pt(9)
                
    # 5. Education Section
    education = cv_data.get('education', [])
    if not education:
        education = [
            {"institution": "CDAC - Centre for Development of Advanced Computing", "location": "Bandra, MH, India", "degree": "Post Graduation Diploma", "graduation_year": "Aug 2024 -- May 2025"},
            {"institution": "MIT World Peace University, Pune", "location": "Pune, MH, India", "degree": "Bachelor of Technology in Electronics & Communication Engineering", "graduation_year": "Sep 2021 -- Jul 2024"}
        ]
    if education:
        add_section_heading("EDUCATION")
        for edu in education:
            inst = edu.get('institution', '')
            e_loc = edu.get('location', '')
            deg = edu.get('degree', '')
            if edu.get('major'):
                deg += f" in {edu.get('major')}"
            e_dates = edu.get('graduation_year', '')
            
            tbl_edu = doc.add_table(rows=2, cols=2)
            tbl_edu.autofit = False
            tbl_edu.columns[0].width = Inches(5.2)
            tbl_edu.columns[1].width = Inches(2.3)
            
            p_i = tbl_edu.cell(0, 0).paragraphs[0]
            p_i.paragraph_format.space_after = Pt(0)
            r_i = p_i.add_run(inst)
            r_i.bold = True
            r_i.font.size = Pt(9)
            
            p_el = tbl_edu.cell(0, 1).paragraphs[0]
            p_el.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p_el.paragraph_format.space_after = Pt(0)
            r_el = p_el.add_run(e_loc)
            r_el.font.size = Pt(9)
            
            p_dg = tbl_edu.cell(1, 0).paragraphs[0]
            p_dg.paragraph_format.space_after = Pt(0)
            r_dg = p_dg.add_run(deg)
            r_dg.italic = True
            r_dg.font.size = Pt(9)
            
            p_ed = tbl_edu.cell(1, 1).paragraphs[0]
            p_ed.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p_ed.paragraph_format.space_after = Pt(0)
            r_ed = p_ed.add_run(e_dates)
            r_ed.italic = True
            r_ed.font.size = Pt(9)
            
    # 6. Projects Section
    projects = cv_data.get('projects', [])
    if projects:
        add_section_heading("PROJECTS")
        for proj in projects:
            title = proj.get('title', 'Project')
            tech = proj.get('technologies', '')
            
            tbl_p = doc.add_table(rows=1, cols=2)
            tbl_p.autofit = False
            tbl_p.columns[0].width = Inches(4.5)
            tbl_p.columns[1].width = Inches(3.0)
            
            p_pt = tbl_p.cell(0, 0).paragraphs[0]
            p_pt.paragraph_format.space_after = Pt(0)
            r_pt = p_pt.add_run(title)
            r_pt.bold = True
            r_pt.font.size = Pt(9)
            
            p_tc = tbl_p.cell(0, 1).paragraphs[0]
            p_tc.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p_tc.paragraph_format.space_after = Pt(0)
            r_tc = p_tc.add_run(tech)
            r_tc.italic = True
            r_tc.font.size = Pt(9)
            
            if proj.get('description'):
                p_pd = doc.add_paragraph(style='List Bullet')
                p_pd.paragraph_format.space_after = Pt(1.5)
                p_pd.paragraph_format.left_indent = Inches(0.2)
                r_pd = p_pd.add_run(proj.get('description'))
                r_pd.font.size = Pt(9)
                
            for ach in proj.get('achievements', []):
                p_pa = doc.add_paragraph(style='List Bullet')
                p_pa.paragraph_format.space_after = Pt(1.5)
                p_pa.paragraph_format.left_indent = Inches(0.2)
                r_pa = p_pa.add_run(ach)
                r_pa.font.size = Pt(9)
                
    # 7. Certifications & Publications
    certs = cv_data.get('certifications', [])
    if not certs:
        certs = [
            "Co-author of 'User Centric Sensor Array for Real-Time Air Pollutant Surveillance' -- IEEE Xplore (Apr 2024)",
            "Docker for the Absolute Beginner -- Hands On -- DevOps (Udemy, 2025)",
            "Advanced Software Engineering Job Simulation (Walmart Global, 2025)",
            "Full Stack Development Certification (upGrad, 2024)"
        ]
    if certs:
        add_section_heading("CERTIFICATIONS & PUBLICATIONS")
        for cert in certs:
            p_cert = doc.add_paragraph(style='List Bullet')
            p_cert.paragraph_format.space_after = Pt(1.5)
            p_cert.paragraph_format.left_indent = Inches(0.2)
            r_c = p_cert.add_run(cert)
            r_c.font.size = Pt(9)
            
    doc.save(output_path)

def escape_latex(text: str) -> str:
    """Escapes special LaTeX characters in string."""
    if not text:
        return ""
    text = str(text)
    # Mapping of LaTeX special characters
    conv = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    regex = re.compile('|'.join(re.escape(str(key)) for key in sorted(conv.keys(), key=lambda item: -len(item))))
    return regex.sub(lambda match: conv[match.group()], text)

def generate_latex_cv(cv_data: dict, output_path: str, template_path: str = None):
    """Generates a tailored LaTeX resume file using the user's resume_template.tex."""
    if not template_path:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(base_dir, "templates", "resume_template.tex")
        
    template_content = ""
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as tf:
            template_content = tf.read()
            
    contact = cv_data.get('contact_info', {})
    name = escape_latex(contact.get('name', 'Sanjeet Surve'))
    location = escape_latex(contact.get('location', 'Mumbai, MH, India'))
    email = escape_latex(contact.get('email', 'sanjeetsurveofficial@gmail.com'))
    linkedin = escape_latex(contact.get('linkedin', 'linkedin.com/in/sanjeetsurve'))
    
    summary = escape_latex(cv_data.get('professional_summary', ''))
    
    # Format Skills
    skills = cv_data.get('skills', {})
    skills_tex_lines = []
    if skills:
        for skill_type, skill_list in skills.items():
            if skill_list:
                label = escape_latex(skill_type.replace('_', ' ').title())
                val = escape_latex(', '.join(skill_list))
                skills_tex_lines.append(f"    \\resumeSectionType{{{label}}}{{:}}{{{val}}}")
    skills_tex = "\n".join(skills_tex_lines)
    
    # Format Experience
    exp_tex_lines = []
    for job in cv_data.get('work_experience', []):
        comp = escape_latex(job.get('company', 'WRXFLO Software Pvt Ltd'))
        loc = escape_latex(job.get('location', 'Mumbai, MH, India'))
        role = escape_latex(job.get('role', 'Quality Assurance Engineer'))
        dates = escape_latex(f"{job.get('start_date', 'Sept 2025')} -- {job.get('end_date', 'Present')}")
        exp_tex_lines.append(f"    \\resumeQuadHeading{{{comp}}}{{{loc}}}\n    {{{role}}}{{{dates}}}")
        exp_tex_lines.append("      \\resumeItemListStart{}")
        for ach in job.get('achievements', []):
            exp_tex_lines.append(f"        \\resumeItem{{{escape_latex(ach)}}}")
        exp_tex_lines.append("      \\resumeItemListEnd{}")
    exp_tex = "\n".join(exp_tex_lines)
    
    # Format Projects
    proj_tex_lines = []
    for proj in cv_data.get('projects', []):
        p_title = escape_latex(proj.get('title', 'Project'))
        p_tech = escape_latex(proj.get('technologies', ''))
        p_desc = escape_latex(proj.get('description', ''))
        proj_tex_lines.append(f"    \\resumeTrioHeading{{{p_title}}}{{{p_tech}}}{{}}")
        proj_tex_lines.append("      \\resumeItemListStart{}")
        if p_desc:
            proj_tex_lines.append(f"        \\resumeItem{{{p_desc}}}")
        for ach in proj.get('achievements', []):
            proj_tex_lines.append(f"        \\resumeItem{{{escape_latex(ach)}}}")
        proj_tex_lines.append("      \\resumeItemListEnd{}")
    proj_tex = "\n".join(proj_tex_lines)
    
    if template_content:
        # Replace sections cleanly in user's template
        # 1. Summary
        if summary:
            template_content = re.sub(
                r'(\\section\{[^}]+\}\s*\\small\{\s*\\textit\{)(.*?)(\}\s*\})',
                r'\g<1>' + summary.replace('\\', r'\\') + r'\g<3>',
                template_content,
                flags=re.DOTALL
            )
        # 2. Technical Skills
        if skills_tex:
            template_content = re.sub(
                r'(\\section\{Technical Skills\}\s*\\resumeHeadingListStart\{\})(.*?)(\\resumeHeadingListEnd\{\})',
                r'\g<1>\n' + skills_tex.replace('\\', r'\\') + r'\n  \g<3>',
                template_content,
                flags=re.DOTALL
            )
        # 3. Experience
        if exp_tex:
            template_content = re.sub(
                r'(\\section\{Experience\}\s*\\resumeHeadingListStart\{\})(.*?)(\\resumeHeadingListEnd\{\}\s*%(?:-+)?\s*\n\s*\\section\{Education\})',
                r'\g<1>\n' + exp_tex.replace('\\', r'\\') + r'\n  \g<3>',
                template_content,
                flags=re.DOTALL
            )
        # 4. Projects
        if proj_tex:
            template_content = re.sub(
                r'(\\section\{Projects\}\s*\\resumeHeadingListStart\{\})(.*?)(\\resumeHeadingListEnd\{\}\s*%(?:-+)?\s*\n\s*\\section\{Certifications)',
                r'\g<1>\n' + proj_tex.replace('\\', r'\\') + r'\n  \g<3>',
                template_content,
                flags=re.DOTALL
            )
        out_content = template_content
    else:
        out_content = f"""\\documentclass[a4paper,11pt]{{article}}
\\begin{{document}}
\\section{{{name}}}
{summary}
\\end{{document}}
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(out_content)

def generate_docx_cover_letter(cl_data: dict, output_path: str):
    doc = docx.Document()
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)
    charcoal = RGBColor(0x2D, 0x37, 0x48)
    navy_blue = RGBColor(0x1A, 0x36, 0x5D)
    
    def add_p(text, font_size=11, bold=False, space_after=10, italic=False, color=charcoal):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(space_after)
        run = p.add_run(text)
        run.bold = bold
        run.italic = italic
        run.font.size = Pt(font_size)
        run.font.color.rgb = color
        return p

    current_date = cl_data.get('date') or datetime.now().strftime("%B %d, %Y")
    add_p(current_date, space_after=15)
    add_p(cl_data.get('recipient_name', 'Hiring Manager / Recruiter'), space_after=2)
    add_p(cl_data.get('company_name', 'Company Name'), space_after=10)
    add_p(cl_data.get('subject', 'Application'), bold=True, color=navy_blue, space_after=12)
    add_p(cl_data.get('salutation', 'Dear Hiring Manager,'), space_after=10)
    add_p(cl_data.get('opening_paragraph', ''), space_after=10)
    for para in cl_data.get('body_paragraphs', []):
        add_p(para, space_after=10)
    add_p(cl_data.get('closing_paragraph', ''), space_after=10)
    add_p(cl_data.get('sign_off', 'Sincerely,'), space_after=5)
    add_p(cl_data.get('sender_name', 'Candidate Name'), bold=True, color=navy_blue, space_after=0)
    doc.save(output_path)

def generate_tailored_documents(cv_path: str, job: dict, model: str, output_base_dir: str = "outputs"):
    try:
        from src.tailor_cv.pdf_parser import extract_text_from_pdf
        cv_text = extract_text_from_pdf(cv_path)
        
        from src.tailor_cv.claude_client import accumulate_job_tokens, get_llm_client
        client = get_llm_client(model=model)
        
        from src.config import Config
        provider_name = Config.get_active_provider().upper()
        print(f"  \n[Tailoring CV] Calling LLM ({provider_name}) for '{job.get('title')}' at '{job.get('company')}'...\n")
        cv_data = get_tailored_cv_data(client, cv_text, job)
        if hasattr(client, 'last_usage') and client.last_usage:
            accumulate_job_tokens(job, client.last_usage)
        
        time.sleep(2.0)
        
        print(f"  [Tailoring Cover Letter] Calling LLM ({provider_name}) for '{job.get('title')}' at '{job.get('company')}'...")
        cl_data = get_tailored_cl_data(client, cv_text, job)
        if cl_data and isinstance(cl_data, dict):
            cl_data['date'] = datetime.now().strftime("%B %d, %Y")
        if hasattr(client, 'last_usage') and client.last_usage:
            accumulate_job_tokens(job, client.last_usage)
        
        company_clean = sanitize_filename(job.get('company', 'Unknown_Company'))
        title_clean = sanitize_filename(job.get('title', 'Unknown_Title'))
        sr_no = job.get('sr_no')
        if sr_no is not None:
            folder_name = f"{sr_no}_{company_clean}_{title_clean}"
        else:
            folder_name = f"{company_clean}_{title_clean}"
        target_dir = os.path.join(output_base_dir, folder_name)
        os.makedirs(target_dir, exist_ok=True)
        
        cv_pdf_path = os.path.join(target_dir, "tailored_cv.pdf")
        cv_docx_path = os.path.join(target_dir, "tailored_cv.docx")
        cl_pdf_path = os.path.join(target_dir, "cover_letter.pdf")
        cl_docx_path = os.path.join(target_dir, "cover_letter.docx")
        
        generate_pdf_cv(cv_data, cv_pdf_path)
        generate_docx_cv(cv_data, cv_docx_path)
        generate_pdf_cover_letter(cl_data, cl_pdf_path)
        generate_docx_cover_letter(cl_data, cl_docx_path)
        
        # Get tailored ATS score
        print(f"  \n[ATS Scanner] Simulating ATS match score for tailored CV...\n")
        ats_score = get_tailored_ats_score(client, cv_data, job)
        job["ats_score"] = ats_score
        if hasattr(client, 'last_usage') and client.last_usage:
            accumulate_job_tokens(job, client.last_usage)
        
        # Save job details as JSON in the same folder
        job_json_path = os.path.join(target_dir, "job_details.json")
        with open(job_json_path, 'w', encoding='utf-8') as jf:
            json.dump(job, jf, indent=2, ensure_ascii=False)
            
        print(f"  \n[Completed] Saved tailored CV, Cover Letter, and Job Details in: {target_dir} (ATS Score: {ats_score})\n")
        return ats_score
    except Exception as e:
        print(f"  [Error] Failed to generate tailored documents for '{job.get('title')}' at '{job.get('company')}': {e}")
        return None
