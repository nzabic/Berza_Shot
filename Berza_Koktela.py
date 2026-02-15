from flask import Flask, jsonify, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler
from datetime import datetime, timedelta
from sqlalchemy import func


# ============================================================
# PROMO VIDEOS VARIABLES
# ============================================================
# Menjati po potrebi
CLIP_DELAY_SECONDS = 300     #  after server start
PAUSE_BETWEEN_PROMO = 5          # Pauza izmedju dve promocija (u minutima)
PROMO_SECONDS = 120               # Trajanje promocije (u sekundama)
REPLAY_INTERVAL = 20            # Na koliko je video ponavlja u toku jedne promocije (u sekundama)

PROMO_KOKTELI = [

{"CLIP_COCKTAIL_NAME": "CUBA LIBRE", "cena": 450, "video": "cuba_libre_v1.mp4"},
{"CLIP_COCKTAIL_NAME": "MAI TAI", "cena": 550, "video": "mai_tai_v3.mp4"},
{"CLIP_COCKTAIL_NAME": "DEVILS ICE TEA", "cena": 590, "video": "devils_v3.mp4"},
{"CLIP_COCKTAIL_NAME": "HERO", "cena": 530, "video": "hero_v1.mp4"},
{"CLIP_COCKTAIL_NAME": "LA ICE TEA", "cena": 580, "video": "la_ice_tea_v2.mp4"},
{"CLIP_COCKTAIL_NAME": "COSMOPOLITAN", "cena": 450, "video": "cosmo_v4.mp4"},
{"CLIP_COCKTAIL_NAME": "JAPANESE SLIPPER", "cena": 550, "video": "jap_slipper_v3.mp4"}

# {"CLIP_COCKTAIL_NAME": "", "cena":, "video": ".mp4"},
# {"CLIP_COCKTAIL_NAME": "", "cena":, "video": ".mp4"},
# {"CLIP_COCKTAIL_NAME": "", "cena":, "video": ".mp4"},
# {"CLIP_COCKTAIL_NAME": "", "cena":, "video": ".mp4"}

                ]
# Promocije (promo cena / puna cena):

# Cuba libre 450  / 580
# Mai Tai 550 / 640
# Devils 590 / 690
# Hero 530 / 650
# LA Ice Tea 580 / 650
# Cosmo 450 / 580
# Japanese Slipper 550 / 630

# "ADIOS MOTHERFUCKER": 666,
# "BAHAMA MAMA": 630,
# "BEAST": 690,
# "BLACK SABATH": 630,
# "BLUE FROG": 650,
# "BLUE LAGOON": 610,
# "LONG ISLAND ICE TEA": 670,
# "MARGARITA KOKTEL": 580,
# "SEX ON THE BEACH": 630,
# "SHOOTIRANJE": 666,
# "STOPER": 666,
# "TEQUILA SUNRISE": 630,
# "VISKI SOUR": 630,


# Ne menjati
current_index = 0
last_cycle_end_time = None
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
    bazna_cena = db.Column(db.Integer, nullable=False)

    trenutna_cena = db.Column(db.Integer, nullable=False)
    prethodna_cena = db.Column(db.Integer, nullable=False)

    minimalna_cena = db.Column(db.Integer, nullable=False)
    maksimalna_cena = db.Column(db.Integer, nullable=False)

    transakcije = db.relationship(
        'Transakcija',
        backref='koktel',
        lazy=True,
        cascade="all, delete-orphan"
    )

    def postavi_limite(self):
        self.minimalna_cena = int(round(self.bazna_cena * 0.70))
        self.maksimalna_cena = int(round(self.bazna_cena * 1,40))

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
    return max(min_cena, min(int(round(nova)), max_cena))


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

        cutoff = datetime.utcnow() - timedelta(seconds=120)

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
        global current_index, last_cycle_end_time, clip_triggered

        elapsed_since_start = (datetime.utcnow() - SERVER_START_TIME).total_seconds()
        if elapsed_since_start < CLIP_DELAY_SECONDS:
            return jsonify({"play": False})

        config = PROMO_KOKTELI[current_index]

        if clip_triggered:
            return jsonify({
                "play": True,
                "clip": config["video"],
                "name": config["CLIP_COCKTAIL_NAME"],
                "price": config["cena"],
                "REPLAY_INTERVAL": REPLAY_INTERVAL,
                "PROMO_SECONDS": PROMO_SECONDS
            })

        # Proveravamo pauzu izmedju promocija
        if last_cycle_end_time:
            # print("\n\n\n last_cycle_end_time \n\n\n")
            #
            # print("datetime.utcnow()", datetime.utcnow())
            # print("last_cycle_end_time", last_cycle_end_time),
            # print("timedelta", timedelta(minutes=PAUSE_BETWEEN_PROMO))
            if datetime.utcnow() - last_cycle_end_time <= timedelta(minutes=PAUSE_BETWEEN_PROMO):
                return jsonify({"play": False})

        # Check price for the specific cocktail currently in rotation
        cocktail_db = Koktel.query.filter_by(naziv=config["CLIP_COCKTAIL_NAME"]).first()

        if cocktail_db and cocktail_db.trenutna_cena >= config["cena"]:

            print("Send request to play video: ", config["video"])
            clip_triggered = True
            return jsonify({
                "play": True,
                "clip": config["video"],
                "name": config["CLIP_COCKTAIL_NAME"],
                "price": config["cena"],
                "REPLAY_INTERVAL": REPLAY_INTERVAL,
                "PROMO_SECONDS": PROMO_SECONDS
            })

        return jsonify({"play": False})

    @app.route('/api/next_cocktail')
    def next_cocktail():
        global current_index, clip_triggered, last_cycle_end_time
        clip_triggered = False
        last_cycle_end_time = datetime.utcnow()  # Zapocinjemo pauzu
        current_index = (current_index + 1) % len(PROMO_KOKTELI) # Prolazimo kroz listu koktela
        return jsonify({"status": "moved to next"})

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
# Promene cene koktela
def podesi_scheduler(app):
    scheduler.add_job(
        id='AzuriranjeCenaJob',
        func=azuriraj_cene_koktela,
        args=[app],
        trigger='interval',
        seconds=120,
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