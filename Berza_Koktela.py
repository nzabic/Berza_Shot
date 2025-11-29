from flask import Flask, jsonify, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler
from datetime import datetime, timedelta
from sqlalchemy import func


# ============================================================
# 1. KONFIGURACIJA APLIKACIJE
# ============================================================

class Config:
    """Konfiguraciona klasa za Flask aplikaciju."""
    SQLALCHEMY_DATABASE_URI = 'sqlite:///berza_koktela.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SCHEDULER_API_ENABLED = True


db = SQLAlchemy()
scheduler = APScheduler()


def kreiraj_aplikaciju():
    """Kreira Flask aplikaciju, povezuje je sa SQLAlchemy i APScheduler-om."""
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    scheduler.init_app(app)

    return app


# ============================================================
# 2. MODELI BAZE PODATAKA
# ============================================================

class Koktel(db.Model):
    """Model za tabelu koktela."""

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
        """
        Automatski računa minimalnu i maksimalnu cenu na osnovu bazne cene.
        Minimalna = 70% bazne cene
        Maksimalna = 130% bazne cene
        """
        self.minimalna_cena = round(self.bazna_cena * 0.70, 2)
        self.maksimalna_cena = round(self.bazna_cena * 1.30, 2)

    def __init__(self, **kwargs):
        """
        Prilikom kreiranja koktela, ako korisnik ne prosledi min/max cenu,
        oni se automatski izračunavaju iz bazne cene.
        """
        super().__init__(**kwargs)

        if "minimalna_cena" not in kwargs or "maksimalna_cena" not in kwargs:
            self.postavi_limite()

    def postavi_novu_cenu(self, nova):
        """Ažurira trenutnu i prethodnu cenu koktela."""
        self.prethodna_cena = self.trenutna_cena
        self.trenutna_cena = round(nova, 2)

    def __repr__(self):
        return f'<Koktel {self.naziv} Cena: {self.trenutna_cena:.2f}>'


class Transakcija(db.Model):
    """Model za svaku pojedinačnu prodaju koktela."""

    id = db.Column(db.Integer, primary_key=True)
    koktel_id = db.Column(db.Integer, db.ForeignKey('koktel.id'), nullable=False)

    kolicina = db.Column(db.Integer, nullable=False)
    broj_stola = db.Column(db.String(10), nullable=False)
    cena_pri_narudzbi = db.Column(db.Float, nullable=False)

    vremenska_oznaka = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class IstorijaCena(db.Model):
    """Model koji čuva svaku promenu cene koktela."""

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
    """
    Pravilo za menjanje cena koktela:
    - ako je prodato > 0, cena raste 1% po komadu
    - ako nije prodato ništa, cena opada 2%
    - cena se ograničava u [min_cena, max_cena]
    """
    if prodato > 0:
        nova = stara * (1 + prodato * 0.01)
    else:
        nova = stara * 0.98

    return max(min_cena, min(round(nova, 2), max_cena))


def validiraj_unos(request):
    """Validira POST unos za narudžbine."""
    try:
        koktel_id = int(request.form.get('koktel_id'))
        kolicina = int(request.form.get('kolicina'))
        broj_stola = request.form.get('broj_stola').strip()

        if kolicina <= 0 or not broj_stola:
            raise ValueError()

        return koktel_id, kolicina, broj_stola

    except Exception:
        return None


# ============================================================
# 4. AUTOMATSKA PROMENA CENA (SCHEDULER)
# ============================================================

def azuriraj_cene_koktela(app):
    """
    Scheduler funkcija — izvršava se svakih 30 sekundi.
    Računa prodaju u poslednjih 30 sekundi i menja cene koktela.
    """
    with app.app_context():

        cutoff = datetime.utcnow() - timedelta(seconds=30)

        podaci = db.session.query(
            Transakcija.koktel_id,
            func.sum(Transakcija.kolicina).label("ukupno")
        ).filter(
            Transakcija.vremenska_oznaka >= cutoff
        ).group_by(
            Transakcija.koktel_id
        ).all()

        mapa_prodaje = {p.koktel_id: p.ukupno for p in podaci}

        for koktel in Koktel.query.all():
            prodato = mapa_prodaje.get(koktel.id, 0)
            stara = koktel.trenutna_cena

            nova = racunaj_novu_cenu(
                stara,
                prodato,
                koktel.minimalna_cena,
                koktel.maksimalna_cena
            )

            if nova != round(stara, 2):
                db.session.add(IstorijaCena(
                    koktel_id=koktel.id,
                    stara_cena=stara,
                    nova_cena=nova,
                    razlog=f"{prodato} prodato"
                ))

            koktel.postavi_novu_cenu(nova)

        db.session.commit()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Cene azurirane.")


# ============================================================
# 5. RUTE
# ============================================================

def registruj_rute(app):

    @app.route('/tv')
    def tv_ekran():
        return render_template('tv_ekran.html')

    @app.route('/api/cene_uzivo')
    def api_cene_uzivo():
        return jsonify([
            {
                'id': k.id,
                'naziv': k.naziv,
                'cena': round(k.trenutna_cena, 2),
                'smer': 1 if k.trenutna_cena > k.prethodna_cena else
                        -1 if k.trenutna_cena < k.prethodna_cena else 0
            }
            for k in Koktel.query.all()
        ])

    @app.route('/transakcije')
    def pregled_transakcija():
        transakcije = Transakcija.query.order_by(
            Transakcija.vremenska_oznaka.desc()
        ).limit(50).all()

        return render_template('pregled_transakcija.html', transakcije=transakcije)

    @app.route("/api/cene_sa_baznom")
    def cene_sa_baznom():
        return jsonify([
            {
                "id": k.id,
                "naziv": k.naziv,
                "cena": k.trenutna_cena,
                "bazna": k.bazna_cena
            }
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
                nova_trans = Transakcija(
                    koktel_id=koktel.id,
                    kolicina=kolicina,
                    broj_stola=broj_stola,
                    cena_pri_narudzbi=koktel.trenutna_cena,
                    vremenska_oznaka=datetime.utcnow()
                )

                db.session.add(nova_trans)
                db.session.commit()

                return redirect(url_for('unos_narudzbe'))

        return render_template('unos_narudzbe.html', kokteli=kokteli)

    @app.route('/dashboard')
    def dashboard():
        """Dashboard sa grafikonima istorije cena i prodaje."""
        kokteli = Koktel.query.all()
        return render_template('dashboard.html', kokteli=kokteli)

    @app.route('/api/istorija_cena/<int:koktel_id>')
    def api_istorija_cena(koktel_id):
        """API: vraća istoriju promena cena za zadati koktel."""
        podaci = IstorijaCena.query.filter_by(koktel_id=koktel_id) \
                                   .order_by(IstorijaCena.vremenska_oznaka.asc()) \
                                   .all()

        return jsonify([
            {
                "vreme": h.vremenska_oznaka.strftime("%Y-%m-%d %H:%M:%S"),
                "stara": h.stara_cena,
                "nova": h.nova_cena
            }
            for h in podaci
        ])

    @app.route('/api/prodaja/<int:koktel_id>')
    def api_prodaja(koktel_id):
        """
        API: agregirana prodaja po vremenu za zadati koktel.
        Grupisanje po minuti (format YYYY-MM-DD HH:MM).
        Napomena: func.strftime radi na SQLite-u; za druge baze treba prilagoditi.
        """
        podaci = db.session.query(
            func.sum(Transakcija.kolicina).label("ukupno"),
            func.strftime("%Y-%m-%d %H:%M", Transakcija.vremenska_oznaka)
        ).filter(
            Transakcija.koktel_id == koktel_id
        ).group_by(
            func.strftime("%Y-%m-%d %H:%M", Transakcija.vremenska_oznaka)
        ).order_by(
            func.min(Transakcija.vremenska_oznaka)
        ).all()

        return jsonify([
            {"vreme": t[1], "kolicina": t[0]}
            for t in podaci
        ])


# ============================================================
# 6. INICIJALIZACIJA BAZE
# ============================================================

def inicijalizuj_bazu():
    """
    Kreira tabele i dodaje početne koktele.
    Limiti se automatski računaju, nije ih potrebno unositi ručno.
    """
    db.create_all()

    if not Koktel.query.first():

        kokteli = [
            Koktel(
                naziv='Margarita',
                bazna_cena=10.00,
                trenutna_cena=10.00,
                prethodna_cena=10.00
            ),
            Koktel(
                naziv='Mojito',
                bazna_cena=9.50,
                trenutna_cena=9.50,
                prethodna_cena=9.50
            ),
            Koktel(
                naziv='Old Fashioned',
                bazna_cena=12.00,
                trenutna_cena=12.00,
                prethodna_cena=12.00
            )
        ]

        db.session.add_all(kokteli)
        db.session.commit()
        print("Početni kokteli dodati sa automatskim limitima.")


# ============================================================
# 7. SCHEDULER
# ============================================================

def podesi_scheduler(app):
    """Registruje periodični APScheduler zadatak."""
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
# 8. MAIN — POKRETANJE APLIKACIJE
# ============================================================

def main():
    app = kreiraj_aplikaciju()
    registruj_rute(app)

    with app.app_context():
        inicijalizuj_bazu()

    podesi_scheduler(app)

    app.run(debug=True, use_reloader=False)


if __name__ == '__main__':
    main()
