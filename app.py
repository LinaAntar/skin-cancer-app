from flask import Flask, render_template, request, redirect, session, flash
import os
import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
from werkzeug.utils import secure_filename
import mysql.connector

app = Flask(__name__)
app.secret_key = "secret"

UPLOAD_FOLDER = "static/uploads/"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

model = load_model("model/vgg16_malignant_vs_benign.h5")

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="skin_cancer_db"
    )

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user" not in session:
        return redirect("/")
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username = %s", (session["user"],))
    user = cursor.fetchone()

    if request.method == "POST":
        full_name = request.form["full_name"]
        specialty = request.form["specialty"]
        phone = request.form["phone"]
        
        # Photo upload
        photo_path = user["photo"]
        if "photo" in request.files:
            file = request.files["photo"]
            if file and file.filename != "":
                filename = secure_filename(file.filename)
                photo_path = os.path.join("static/uploads/", filename)
                os.makedirs("static/uploads/", exist_ok=True)
                file.save(photo_path)

        cursor.execute("""
            UPDATE users SET full_name=%s, specialty=%s, phone=%s, photo=%s 
            WHERE username=%s
        """, (full_name, specialty, phone, photo_path, session["user"]))
        db.commit()
        flash("Profil mis à jour ✓", "success")
        return redirect("/profile")

    cursor.close()
    db.close()
    return render_template("profile.html", user=user)
# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pwd  = request.form["password"]

        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (user,))
        result = cursor.fetchone()
        cursor.close()
        db.close()

        if result and result["password"] == pwd:
            session["user"] = user
            flash("Login réussi ✓", "success")
            return redirect("/dashboard")
        else:
            flash("Identifiant ou mot de passe incorrect ✗", "danger")

    return render_template("login.html")

# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM patients")
    total = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) as count FROM patients WHERE result = 'Malignant'")
    malignant = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM patients WHERE result = 'Benign'")
    benign = cursor.fetchone()["count"]
    cursor.close()
    db.close()

    return render_template("dashboard.html", total=total, malignant=malignant, benign=benign)

# ─────────────────────────────────────────────
# PREDICT
# ─────────────────────────────────────────────

@app.route("/predict", methods=["GET", "POST"])
def predict():
    if "user" not in session:
        return redirect("/")

    if request.method == "POST":
        try:
            name = request.form["name"]
            age  = request.form["age"]
            file = request.files["image"]

            if file.filename == "":
                flash("Veuillez choisir une image", "warning")
                return redirect("/predict")

            if not allowed_file(file.filename):
                flash("Format non supporté (png, jpg, jpeg uniquement)", "warning")
                return redirect("/predict")

            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(path)

            # Prétraitement image pour VGG16
            img = image.load_img(path, target_size=(224, 224))
            img = image.img_to_array(img) / 255.0
            img = np.expand_dims(img, axis=0)

            # Prédiction
            pred   = model.predict(img)[0][0]
            result = "Malignant" if pred > 0.5 else "Benign"

            # Sauvegarde en base
            db     = get_db()
            cursor = db.cursor()
            cursor.execute(
                """
                INSERT INTO patients (name, age, result, probability, image_path)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (name, age, result, float(pred), path)
            )
            db.commit()
            cursor.close()
            db.close()

            flash("Analyse réussie ✓", "success")
            return render_template(
                "result.html",
                result=result,
                prob=round(pred * 100, 2),
                img_path=path
            )

        except Exception as e:
            print(f"[ERREUR predict] {e}")
            flash(f"Erreur système : {e}", "danger")
            return redirect("/predict")

    return render_template("predict.html")

# ─────────────────────────────────────────────
# PATIENTS
# ─────────────────────────────────────────────

@app.route("/patients")
def patients():
    if "user" not in session:
        return redirect("/")

    filter = request.args.get("filter", "all")
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if filter in ["Malignant", "Benign"]:
        cursor.execute("SELECT * FROM patients WHERE result = %s ORDER BY created_at DESC", (filter,))
    else:
        cursor.execute("SELECT * FROM patients ORDER BY created_at DESC")
    
    data = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template("patients.html", patients=data, filter=filter)
# ─────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────

@app.route("/logout")
def logout():
    session.clear()
    flash("Déconnecté", "info")
    return redirect("/")


@app.route("/delete/<int:id>")
def delete(id):
    if "user" not in session:
        return redirect("/")
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM patients WHERE id = %s", (id,))
    db.commit()
    cursor.close()
    db.close()
    flash("Patient supprimé ✓", "success")
    return redirect("/patients")
# ─────────────────────────────────────────────

if __name__ == "__main__":

    app.run(debug=True)

