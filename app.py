from flask import Flask
from flask import render_template
from flask import request
from flask import redirect
from flask import session
from flask_sqlalchemy import SQLAlchemy
from flask import jsonify
from datetime import datetime

app = Flask(__name__)
app.secret_key = "railway_secret"

app.config.from_object("config.Config")

db = SQLAlchemy(app)

@app.route("/")
def home():
    return "Railway DPMS Running"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        result = db.session.execute(
            db.text("""
                SELECT *
                FROM users
                WHERE username = :username
            """),
            {"username": username}
        )

        user = result.fetchone()

        if user and password == user.password_hash:
            role = user.role.strip()

            session["user_id"] = user.id
            session["role"] = role
            session["department_id"] = user.department_id
            session["username"] = user.username

            if role == "LEVEL1":
                return redirect("/department")
            elif role == "LEVEL2":
                return redirect("/hod")
            elif role == "LEVEL3":
                return redirect("/nodal")
            elif role == "LEVEL4":
                return redirect("/adrm")
            elif role == "LEVEL5":
                return redirect("/drm")
            elif role == "ADMIN":
                return redirect("/admin")

        return "Invalid Login"

    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    return f"""
    <h1>Railway DPMS Dashboard</h1>
    User ID : {session['user_id']} <br>
    Role : {session['role']} <br>
    Department : {session['department_id']}
    """

@app.route("/drm")
def drm():
    if "user_id" not in session:
        return redirect("/login")

    if session["role"] != "LEVEL5":
        return "Access Denied"

    result = db.session.execute(
        db.text("""
            SELECT
                md.id,
                md.performance_month,
                md.cumulative_performance,
                md.status,
                md.remarks,
                k.kpi_name
            FROM monthly_data md
            JOIN kpis k
            ON md.kpi_id = k.id
            WHERE md.status = 'FORWARDED_TO_DRM'
            ORDER BY md.created_at DESC
        """)
    )

    rows = result.fetchall()

    return render_template(
        "drm.html",
        rows=rows
    )

@app.route("/freeze/<int:id>")
def freeze(id):
    if "user_id" not in session:
        return redirect("/login")

    if session["role"] != "LEVEL5":
        return "Access Denied"

    db.session.execute(
        db.text("""
            UPDATE monthly_data
            SET status='FROZEN'
            WHERE id=:id
        """),
        {"id": id}
    )

    db.session.commit()
    return redirect("/drm")

@app.route("/testdb")
def testdb():
    try:
        db.session.execute(db.text("SELECT 1"))
        return "Database Connected Successfully"
    except Exception as e:
        return str(e)

@app.route("/debuguser")
def debuguser():
    result = db.session.execute(db.text("SELECT * FROM users"))
    rows = result.fetchall()
    return str(rows)

@app.route("/debug/returned")
def debug_returned():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    
    result = db.session.execute(
        db.text("""
            SELECT 
                md.id,
                md.kpi_id,
                md.performance_month,
                md.cumulative_performance,
                md.status,
                md.remarks,
                md.month,
                md.year,
                md.entered_by,
                k.kpi_name
            FROM monthly_data md
            JOIN kpis k ON md.kpi_id = k.id
            WHERE md.entered_by = :user_id
            AND md.status = 'RETURNED'
            ORDER BY md.created_at DESC
        """),
        {"user_id": session["user_id"]}
    )
    
    rows = result.fetchall()
    
    return jsonify({
        "count": len(rows),
        "rows": [dict(row._mapping) for row in rows]
    })

@app.route("/remove_return/<int:id>", methods=["POST"])
def remove_return(id):
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Login required"}), 401
    
    try:
        # First verify that this return entry belongs to the logged-in user and has RETURNED status
        result = db.session.execute(
            db.text("""
                SELECT id, kpi_id, month, year 
                FROM monthly_data 
                WHERE id = :id 
                AND entered_by = :user_id 
                AND status = 'RETURNED'
            """),
            {"id": id, "user_id": session["user_id"]}
        )
        
        record = result.fetchone()
        
        if not record:
            return jsonify({"success": False, "message": "Record not found or you don't have permission to delete it"}), 403
        
        # Delete the returned entry
        db.session.execute(
            db.text("DELETE FROM monthly_data WHERE id = :id"),
            {"id": id}
        )
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": "Returned KPI removed successfully. You can now enter fresh data."
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error removing returned item: {str(e)}")
        return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500

@app.route("/department", methods=["GET", "POST"])
def department():
    if "user_id" not in session:
        return redirect("/login")

    user_department = session["department_id"]
    selected_month = request.values.get("month", "JUNE")
    selected_year = request.values.get("year", "2026")
    
    try:
        selected_year = int(selected_year)
    except ValueError:
        selected_year = 2026

    result = db.session.execute(
        db.text("""
            SELECT
                k.*,
                d.dept_name,
                md.performance_month,
                md.cumulative_performance,
                md.status,
                md.remarks,
                prev.performance_month AS previous_year_value,
                prev.cumulative_performance AS previous_year_cumulative
            FROM kpis k
            JOIN departments d
            ON k.department_id = d.id
            LEFT JOIN monthly_data md
            ON md.kpi_id = k.id
            AND md.entered_by = :user_id
            AND md.month = :month
            AND md.year = :year
            LEFT JOIN monthly_data prev
            ON prev.kpi_id = k.id
            AND prev.entered_by = :user_id
            AND prev.month = :month
            AND prev.year = :previous_year
            ORDER BY
                k.display_order,
                k.id
        """),
        {
            "user_id": session["user_id"],
            "month": selected_month,
            "year": selected_year,
            "previous_year": selected_year - 1
        }
    )

    kpis = result.fetchall()

    returned_result = db.session.execute(
        db.text("""
            SELECT
                md.id,
                md.kpi_id,
                md.performance_month,
                md.cumulative_performance,
                md.status,
                md.remarks,
                md.month,
                md.year,
                k.kpi_name
            FROM monthly_data md
            JOIN kpis k ON md.kpi_id = k.id
            WHERE md.entered_by = :user_id
            AND md.status = 'RETURNED'
            ORDER BY md.created_at DESC
        """),
        {
            "user_id": session["user_id"]
        }
    )

    returned_kpis = returned_result.fetchall()

    if request.method == "POST":
        action = request.form.get("action")
        status = "DRAFT"

        if action == "submit":
            status = "SUBMITTED"

        user_department = session["department_id"]

        for kpi in kpis:
            if kpi.department_id != user_department:
                continue

            month_value = request.form.get(f"month_{kpi.id}")
            cumulative_value = request.form.get(f"cum_{kpi.id}")
            prev_cum_value = request.form.get(f"prev_cum_{kpi.id}")
            prev_year_value = request.form.get(f"prev_{kpi.id}")

            if month_value == "":
                month_value = None
            if cumulative_value == "":
                cumulative_value = None
            if prev_cum_value == "":
                prev_cum_value = None
            if prev_year_value == "":
                prev_year_value = None

            if month_value is not None or cumulative_value is not None or prev_year_value is not None or prev_cum_value is not None:
                existing = db.session.execute(
                    db.text("""
                        SELECT id, status
                        FROM monthly_data
                        WHERE kpi_id = :kpi_id
                        AND entered_by = :entered_by
                        AND month = :month
                        AND year = :year
                    """),
                    {
                        "kpi_id": kpi.id,
                        "entered_by": session["user_id"],
                        "month": selected_month,
                        "year": selected_year
                    }
                ).fetchone()

                if existing:
                    new_status = status
                    db.session.execute(
                        db.text("""
                            UPDATE monthly_data
                            SET
                                performance_month = :month_value,
                                cumulative_performance = :cumulative_value,
                                previous_year_value = :prev_year_value,
                                cumulative_performance_of_prev_year = :prev_cum_value,
                                status = :status,
                                remarks = NULL
                            WHERE id = :id
                        """),
                        {
                            "id": existing.id,
                            "month_value": float(month_value) if month_value else None,
                            "cumulative_value": float(cumulative_value) if cumulative_value else None,
                            "prev_year_value": float(prev_year_value) if prev_year_value else None,
                            "prev_cum_value": float(prev_cum_value) if prev_cum_value else None,
                            "status": new_status
                        }
                    )
                else:
                    db.session.execute(
                        db.text("""
                            INSERT INTO monthly_data
                            (
                                kpi_id,
                                month,
                                year,
                                performance_month,
                                previous_year_value,
                                cumulative_performance,
                                cumulative_performance_of_prev_year,
                                entered_by,
                                status
                            )
                            VALUES
                            (
                                :kpi_id,
                                :month,
                                :year,
                                :month_value,
                                :prev_year_value,
                                :cumulative_value,
                                :prev_cum_value,
                                :entered_by,
                                :status
                            )
                        """),
                        {
                            "kpi_id": kpi.id,
                            "month": selected_month,
                            "year": selected_year,
                            "month_value": float(month_value) if month_value else None,
                            "prev_year_value": float(prev_year_value) if prev_year_value else None,
                            "cumulative_value": float(cumulative_value) if cumulative_value else None,
                            "prev_cum_value": float(prev_cum_value) if prev_cum_value else None,
                            "entered_by": session["user_id"],
                            "status": status
                        }
                    )

        db.session.commit()

        returned_result = db.session.execute(
            db.text("""
                SELECT
                    md.id,
                    md.kpi_id,
                    md.performance_month,
                    md.cumulative_performance,
                    md.status,
                    md.remarks,
                    md.month,
                    md.year,
                    k.kpi_name
                FROM monthly_data md
                JOIN kpis k ON md.kpi_id = k.id
                WHERE md.entered_by = :user_id
                AND md.status = 'RETURNED'
                ORDER BY md.created_at DESC
            """),
            {"user_id": session["user_id"]}
        )
        returned_kpis = returned_result.fetchall()

        message = "Draft Saved Successfully" if status == "DRAFT" else "Submitted Successfully"
        
        return render_template(
            "department_form.html",
            kpis=kpis,
            returned_kpis=returned_kpis,
            user_department=session["department_id"],
            message=message,
            selected_month=selected_month,
            selected_year=selected_year
        )

    return render_template(
        "department_form.html",
        kpis=kpis,
        returned_kpis=returned_kpis,
        user_department=session["department_id"],
        selected_month=selected_month,
        selected_year=selected_year
    )

@app.route("/hod")
def hod():
    if "user_id" not in session:
        return redirect("/login")

    if session["role"] != "LEVEL2":
        return "Access Denied"

    department_id = session["department_id"]
    selected_month = request.args.get("month", "JUNE")
    selected_year = request.args.get("year", "2026")

    try:
        selected_year = int(selected_year)
    except ValueError:
        selected_year = 2026

    # Query to get all submitted KPIs with previous year data
    result = db.session.execute(
        db.text("""
            SELECT
                md.id,
                md.performance_month,
                md.cumulative_performance,
                md.status,
                md.month,
                md.year,
                md.remarks,
                md.created_at,
                COALESCE(md.previous_year_value, 0) as previous_year_value,
                COALESCE(md.cumulative_performance_of_prev_year, 0) as cumulative_performance_of_prev_year,
                k.kpi_name,
                COALESCE(k.unit, '') as unit,
                k.annual_target,
                k.section_name,
                d.dept_name
            FROM monthly_data md
            JOIN kpis k ON md.kpi_id = k.id
            JOIN departments d ON k.department_id = d.id
            WHERE md.status = 'SUBMITTED'
            AND k.department_id = :department_id
            AND UPPER(md.month) = UPPER(:month)
            AND md.year = :year
            ORDER BY k.display_order, k.id
        """),
        {
            "department_id": department_id,
            "month": selected_month,
            "year": selected_year
        }
    )

    rows = result.fetchall()
    
    # Convert to list of dictionaries
    rows_list = []
    for row in rows:
        row_dict = {
            'id': row.id,
            'performance_month': row.performance_month if row.performance_month is not None else '-',
            'cumulative_performance': row.cumulative_performance if row.cumulative_performance is not None else '-',
            'status': row.status,
            'month': row.month,
            'year': row.year,
            'remarks': row.remarks,
            'created_at': row.created_at,
            'previous_year_value': row.previous_year_value if row.previous_year_value and row.previous_year_value != 0 else 'Not Available',
            'cumulative_performance_of_prev_year': row.cumulative_performance_of_prev_year if row.cumulative_performance_of_prev_year and row.cumulative_performance_of_prev_year != 0 else 'Not Available',
            'kpi_name': row.kpi_name,
            'unit': row.unit,
            'annual_target': row.annual_target,
            'section_name': row.section_name,
            'dept_name': row.dept_name
        }
        rows_list.append(row_dict)
    
    return render_template(
        "hod_review.html",
        rows=rows_list,
        selected_month=selected_month,
        selected_year=selected_year
    )

@app.route("/approve_bulk", methods=["POST"])
def approve_bulk():
    if "user_id" not in session:
        return jsonify({"message": "Login Required"}), 401

    if session["role"] != "LEVEL2":
        return jsonify({"message": "Access Denied"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"message": "Invalid request data"}), 400
    
    ids = data.get("ids", [])

    if not ids:
        return jsonify({"message": "No KPI Selected"}), 400

    ids = [int(id_val) for id_val in ids]

    try:
        for id_val in ids:
            db.session.execute(
                db.text("""
                    UPDATE monthly_data
                    SET status = 'APPROVED'
                    WHERE id = :id AND status = 'SUBMITTED'
                """),
                {"id": id_val}
            )
        db.session.commit()
        return jsonify({
            "message": f"{len(ids)} KPI(s) Approved Successfully"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error: {str(e)}"}), 500

@app.route("/return/<int:id>", methods=["GET", "POST"])
def return_entry(id):
    if "user_id" not in session:
        return redirect("/login")
    
    if session["role"] != "LEVEL2":
        return "Access Denied"
    
    if request.method == "POST":
        remarks = request.form.get("remarks", "")
        
        try:
            db.session.execute(
                db.text("""
                    UPDATE monthly_data
                    SET status = 'RETURNED',
                        remarks = :remarks
                    WHERE id = :id AND status = 'SUBMITTED'
                """),
                {
                    "id": id,
                    "remarks": remarks
                }
            )
            db.session.commit()
            return redirect("/hod")
        except Exception as e:
            db.session.rollback()
            return f"Error: {str(e)}", 500
    
    # GET request - show the return form
    result = db.session.execute(
        db.text("""
            SELECT 
                md.id,
                k.kpi_name,
                md.performance_month,
                md.cumulative_performance
            FROM monthly_data md
            JOIN kpis k ON md.kpi_id = k.id
            WHERE md.id = :id
        """),
        {"id": id}
    )
    kpi = result.fetchone()
    
    return render_template("return_form.html", kpi=kpi)

@app.route("/nodal")
def nodal():
    if "user_id" not in session:
        return redirect("/login")

    if session["role"] != "LEVEL3":
        return "Access Denied"

    selected_month = request.args.get("month", "JUNE")
    selected_year = request.args.get("year", "2026")
    
    try:
        selected_year = int(selected_year)
    except ValueError:
        selected_year = 2026

    result = db.session.execute(
        db.text("""
            SELECT
                md.id,
                md.performance_month,
                md.cumulative_performance,
                md.status,
                md.remarks,
                k.kpi_name,
                d.dept_name
            FROM monthly_data md
            JOIN kpis k
            ON md.kpi_id = k.id
            JOIN departments d
            ON k.department_id = d.id
            WHERE md.status = 'APPROVED'
            AND md.month = :month
            AND md.year = :year
            ORDER BY k.id
        """),
        {
            "month": selected_month,
            "year": selected_year
        }
    )

    rows = result.fetchall()

    return render_template(
        "nodal.html",
        rows=rows,
        selected_month=selected_month,
        selected_year=selected_year
    )

@app.route("/adrm")
def adrm():
    if "user_id" not in session:
        return redirect("/login")

    if session["role"] != "LEVEL4":
        return "Access Denied"

    selected_month = request.args.get("month", "JUNE")
    selected_year = request.args.get("year", "2026")
    
    try:
        selected_year = int(selected_year)
    except ValueError:
        selected_year = 2026

    result = db.session.execute(
        db.text("""
            SELECT
                md.id,
                md.performance_month,
                md.cumulative_performance,
                md.status,
                md.remarks,
                k.kpi_name,
                d.dept_name
            FROM monthly_data md
            JOIN kpis k
            ON md.kpi_id = k.id
            JOIN departments d
            ON k.department_id = d.id
            WHERE md.status = 'FORWARDED_TO_ADRM'
            AND md.month = :month
            AND md.year = :year
            ORDER BY k.id
        """),
        {
            "month": selected_month,
            "year": selected_year
        }
    )

    rows = result.fetchall()

    return render_template(
        "adrm.html",
        rows=rows,
        selected_month=selected_month,
        selected_year=selected_year
    )

@app.route("/forward_to_drm/<int:id>")
def forward_to_drm(id):
    if "user_id" not in session:
        return redirect("/login")
    
    if session["role"] != "LEVEL4":
        return "Access Denied"
    
    try:
        db.session.execute(
            db.text("""
                UPDATE monthly_data
                SET status='FORWARDED_TO_DRM'
                WHERE id=:id AND status='FORWARDED_TO_ADRM'
            """),
            {"id": id}
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return f"Error: {str(e)}", 500
    
    return redirect("/adrm")

@app.route("/forward_to_adrm/<int:id>")
def forward_to_adrm(id):
    if "user_id" not in session:
        return redirect("/login")
    
    if session["role"] != "LEVEL3":
        return "Access Denied"
    
    try:
        db.session.execute(
            db.text("""
                UPDATE monthly_data
                SET status='FORWARDED_TO_ADRM'
                WHERE id=:id AND status='APPROVED'
            """),
            {"id": id}
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return f"Error: {str(e)}", 500
    
    return redirect("/nodal")

@app.route("/admin/kpis")
def manage_kpis():
    if "user_id" not in session or session["role"] != "ADMIN":
        return redirect("/login")

    result = db.session.execute(
        db.text("""
            SELECT *
            FROM kpis
            ORDER BY display_order
        """)
    )

    kpis = result.fetchall()

    return render_template(
        "manage_kpis.html",
        kpis=kpis
    )

@app.route("/admin/update_kpi/<int:id>", methods=["POST"])
def update_kpi(id):
    if "user_id" not in session or session["role"] != "ADMIN":
        return redirect("/login")

    annual_target = request.form["annual_target"]

    try:
        db.session.execute(
            db.text("""
                UPDATE kpis
                SET annual_target = :annual_target
                WHERE id = :id
            """),
            {
                "annual_target": annual_target,
                "id": id
            }
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return f"Error: {str(e)}", 500

    return redirect("/admin/kpis")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

if __name__ == "__main__":
    app.run(debug=True)