from flask import Flask, jsonify, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler
from datetime import datetime, timedelta
from sqlalchemy import func


# ============================================================
# CLIP CONFIG - change these as needed
# ============================================================
CLIP_FILE = "tramp_mai_tai.mp4"           # filename in static/ folder
CLIP_DELAY_SECONDS = 105         # 1:45 after server start
CLIP_PRICE_THRESHOLD = 550       # Blue Frog price threshold
CLIP_COCKTAIL_NAME = "MAI TAI"

# Runtime state
SERVER_START_TIME = None
clip_triggered = False


# ============================================================
# 1. KONFIGURACIJA APLIKACIJE
# ============================================================

class Config:
    SQLALCHEMY_DATABASE_URI = 'sqlite:///berza_koktela.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SCHEDULER_API_ENABLED = True


db = SQLAlchemy()
scheduler = APScheduler()


def kreiraj_aplikaciju():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    scheduler.init_app(app)
    return app


# ============================================================
# 2. MODELI
# ============================================================

class Koktel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    naziv = db.Column(db.String(80), unique=True, nullable=False)
    bazna_cena = db.Column(db.Float, nullable=False)

    trenutna_cena = db.Column(db.Float, nullable=False)
    prethodna_cena = db.Column(db.Float, nullable=False)

    minimalna_cena = db.Column(db.Float, nullable=False)
    maksimalna_cena = db.Column(db.Float, nullable=False)

    transakcije = db.relationship(
        'Transakcija',
        backref='koktel',
        lazy=True,
        cascade="all, delete-orphan"
    )

    def postavi_limite(self):
        self.minimalna_cena = round(self.bazna_cena * 0.70, 2)
        self.maksimalna_cena = round(self.bazna_cena * 1.30, 2)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.postavi_limite()
        self.trenutna_cena = self.bazna_cena
        self.prethodna_cena = self.bazna_cena

    def postavi_novu_cenu(self, nova):
        self.prethodna_cena = self.trenutna_cena
        self.trenutna_cena = round(nova, 2)


class Transakcija(db.Model):
    """Model za svaku pojedinačnu prodaju koktela."""

    id = db.Column(db.Integer, primary_key=True)
    koktel_id = db.Column(db.Integer, db.ForeignKey('koktel.id'), nullable=False)

    koktel_ime = db.Column(db.String(80), nullable=False)  # ★ ADDED FIELD

    kolicina = db.Column(db.Integer, nullable=False)
    broj_stola = db.Column(db.String(10), nullable=False)
    cena_pri_narudzbi = db.Column(db.Float, nullable=False)
    vremenska_oznaka = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class IstorijaCena(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    koktel_id = db.Column(db.Integer, db.ForeignKey('koktel.id'), nullable=False)
    stara_cena = db.Column(db.Float, nullable=False)
    nova_cena = db.Column(db.Float, nullable=False)
    razlog = db.Column(db.String(100))
    vremenska_oznaka = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# 3. POMOĆNE FUNKCIJE
# ============================================================

def racunaj_novu_cenu(stara, prodato, min_cena, max_cena):
    if prodato > 0:
        nova = stara * (1 + prodato * 0.01)
    else:
        nova = stara * 0.98
    return max(min_cena, min(round(nova, 2), max_cena))


def validiraj_unos(request):
    try:
        return (
            int(request.form["koktel_id"]),
            int(request.form["kolicina"]),
            request.form["broj_stola"].strip()
        )
    except:
        return None


# ============================================================
# 4. AUTOMATSKA PROMENA CENA
# ============================================================

def azuriraj_cene_koktela(app):
    with app.app_context():

        cutoff = datetime.utcnow() - timedelta(seconds=30)

        prodaja = {
            kid: ukupno
            for kid, ukupno in db.session.query(
                Transakcija.koktel_id,
                func.sum(Transakcija.kolicina)
            ).filter(
                Transakcija.vremenska_oznaka >= cutoff
            ).group_by(Transakcija.koktel_id)
        }

        for k in Koktel.query.all():
            stara = k.trenutna_cena

            nova = racunaj_novu_cenu(
                stara,
                prodaja.get(k.id, 0),
                k.minimalna_cena,
                k.maksimalna_cena
            )

            if nova != stara:
                db.session.add(IstorijaCena(
                    koktel_id=k.id,
                    stara_cena=stara,
                    nova_cena=nova,
                    razlog=f"{prodaja.get(k.id, 0)} prodato"
                ))

            k.postavi_novu_cenu(nova)

        db.session.commit()
        print(f"[{datetime.now():%H:%M:%S}] ✔ Ažurirane cene")


# ============================================================
# 5. RUTE
# ============================================================

def registruj_rute(app):

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/tv')
    def tv_ekran():
        return render_template('tv_ekran.html')

    @app.route('/api/cene_uzivo')
    def api_cene_uzivo():
        return jsonify([
            {
                'id': k.id,
                'naziv': k.naziv,
                'cena': k.trenutna_cena,
                'smer':
                    1 if k.trenutna_cena > k.prethodna_cena else
                    -1 if k.trenutna_cena < k.prethodna_cena else
                    0
            }
            for k in Koktel.query.all()
        ])

    @app.route('/api/cene_sa_baznom')
    def cene_sa_baznom():
        return jsonify([
            {"id": k.id, "bazna": k.bazna_cena}
            for k in Koktel.query.all()
        ])

    @app.route('/unos_narudzbe', methods=['GET', 'POST'])
    def unos_narudzbe():
        kokteli = Koktel.query.all()

        if request.method == 'POST':
            podaci = validiraj_unos(request)
            if not podaci:
                return redirect(url_for('unos_narudzbe'))

            koktel_id, kolicina, broj_stola = podaci
            koktel = Koktel.query.get(koktel_id)

            if koktel:
                db.session.add(Transakcija(
                    koktel_id=koktel_id,
                    koktel_ime=koktel.naziv,   # ★ STORE NAME
                    kolicina=kolicina,
                    broj_stola=broj_stola,
                    cena_pri_narudzbi=koktel.trenutna_cena
                ))
                db.session.commit()

                return redirect(url_for('unos_narudzbe'))

        return render_template('unos_narudzbe.html', kokteli=kokteli)

    @app.route('/transakcije')
    def pregled_transakcija():
        transakcije = Transakcija.query.order_by(
            Transakcija.vremenska_oznaka.desc()
        ).all()
        return render_template('pregled_transakcija.html', transakcije=transakcije)

    @app.route('/dashboard')
    def dashboard():
        kokteli = Koktel.query.all()
        return render_template('dashboard.html', kokteli=kokteli)

    @app.route('/api/check_clip')
    def check_clip():
        global clip_triggered

        # Don't trigger again if already played
        if clip_triggered:
            return jsonify({"play": False, "clip": CLIP_FILE})

        # Check time condition
        elapsed = (datetime.utcnow() - SERVER_START_TIME).total_seconds()
        if elapsed < CLIP_DELAY_SECONDS:
            return jsonify({"play": False, "clip": CLIP_FILE})

        # Check price condition
        blue_frog = Koktel.query.filter_by(naziv=CLIP_COCKTAIL_NAME).first()
        if not blue_frog or blue_frog.trenutna_cena <= CLIP_PRICE_THRESHOLD:
            return jsonify({"play": False, "clip": CLIP_FILE})

        # All conditions met - trigger once
        clip_triggered = True
        return jsonify({"play": True, "clip": CLIP_FILE})

    @app.route('/api/reset_clip')
    def reset_clip():
        global clip_triggered, SERVER_START_TIME
        clip_triggered = False
        SERVER_START_TIME = datetime.utcnow()
        return jsonify({"status": "reset", "message": "Clip reset, timer restarted"})

# ============================================================
# 6. INICIJALIZACIJA BAZE
# ============================================================

def inicijalizuj_bazu():

    cocktails = {
        "ADIOS MOTHERFUCKER": 666,
        "BAHAMA MAMA": 630,
        "BEAST": 690,
        "BLACK SABATH": 630,
        "BLUE FROG": 650,
        "BLUE LAGOON": 610,
        "COSMOPOLITAN": 580,
        "CUBA LIBRE": 580,
        "DEVILS ICE TEA": 690,
        "HERO": 650,
        "JAPANESE SLIPPER": 630,
        "LA ICE TEA": 650,
        "LONG ISLAND ICE TEA": 670,
        "MAI TAI": 640,
        "MARGARITA KOKTEL": 580,
        "SEX ON THE BEACH": 630,
        "SHOOTIRANJE": 666,
        "STOPER": 666,
        "TEQUILA SUNRISE": 630,
        "VISKI SOUR": 630,
    }

    db.create_all()

    if not Koktel.query.first():
        kokteli = [
            Koktel(naziv=name, bazna_cena=price)
            for name, price in cocktails.items()
        ]
        db.session.add_all(kokteli)
        db.session.commit()
        print("✔ Početni kokteli dodati")


# ============================================================
# 7. SCHEDULER
# ============================================================

def podesi_scheduler(app):
    scheduler.add_job(
        id='AzuriranjeCenaJob',
        func=azuriraj_cene_koktela,
        args=[app],
        trigger='interval',
        seconds=30,
        max_instances=1,
        coalesce=True
    )
    scheduler.start()


# ============================================================
# 8. MAIN
# ============================================================

def main():
    global SERVER_START_TIME
    SERVER_START_TIME = datetime.utcnow()

    app = kreiraj_aplikaciju()
    registruj_rute(app)

    with app.app_context():
        inicijalizuj_bazu()

    podesi_scheduler(app)

    app.run(debug=True, use_reloader=False)


if __name__ == '__main__':
    main()
