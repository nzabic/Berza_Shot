from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler # Za racunanje cene na svakih 10 minuta?
from datetime import datetime, timedelta
from sqlalchemy import func # Za racunanje u bazi/tabelama
from flask import render_template, request, redirect, url_for  # DODAJEMO ove funkcije za rad sa webom

# --- 1. Inicijalizacija Ekstenzija ---
# SQLAlchemy objekat za upravljanje bazom podataka
db = SQLAlchemy()
scheduler = APScheduler()  # INICIJALIZACIJA SCHEDULERA


def kreiraj_aplikaciju():
    # Kreiranje Flask aplikacije
    aplikacija = Flask(__name__)

    # --- Konfiguracija Aplikacije ---
    # Putanja do SQLite fajla za bazu podataka
    aplikacija.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///berza_koktela.db'
    # Iskljucivanje upozorenja
    aplikacija.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Konfiguracija za APScheduler
    aplikacija.config['SCHEDULER_API_ENABLED'] = True

    # Povezivanje 'db' objekta sa aplikacijom
    db.init_app(aplikacija)

    # Povezivanje 'scheduler' objekta sa aplikacijom
    scheduler.init_app(aplikacija)

    return aplikacija


# --- 2. Modeli Baze Podataka (Tabele) ---

class Koktel(db.Model):
    # Tabela za koktele i njihove trenutne cene
    id = db.Column(db.Integer, primary_key=True)
    naziv = db.Column(db.String(80), unique=True, nullable=False)
    bazna_cena = db.Column(db.Float, nullable=False)

    # Cene koje se menjaju
    trenutna_cena = db.Column(db.Float, nullable=False)
    prethodna_cena = db.Column(db.Float, nullable=False)  # Za strelicu GORE/DOLE

    # NOVE KOLONE ZA LIMITE CENE
    minimalna_cena = db.Column(db.Float, nullable=False)
    maksimalna_cena = db.Column(db.Float, nullable=False)

    # Povezivanje sa tabelom narudzbi
    transakcije = db.relationship('Transakcija', backref='koktel', lazy=True)

    def __repr__(self):
        return f'<Koktel {self.naziv} Cena: {self.trenutna_cena:.2f}>'


class Transakcija(db.Model):
    # Tabela za belezenje svake porudzbine/prodaje
    id = db.Column(db.Integer, primary_key=True)

    # Strani kljuc koji ukazuje na ID koktela
    koktel_id = db.Column(db.Integer, db.ForeignKey('koktel.id'), nullable=False)

    kolicina = db.Column(db.Integer, nullable=False)
    broj_stola = db.Column(db.String(10), nullable=False)

    # Cena po kojoj je koktel narucen (fiksira cenu u trenutku narudzbe)
    cena_pri_narudzbi = db.Column(db.Float, nullable=False)

    # Vremenska oznaka za analizu prodaje u poslednjih 10 minuta
    vremenska_oznaka = db.Column(db.DateTime, index=True, default=datetime.utcnow)


class IstorijaCena(db.Model):
    # Tabela za belezenje svih promena cena (svakih 10 minuta)
    id = db.Column(db.Integer, primary_key=True)
    koktel_id = db.Column(db.Integer, db.ForeignKey('koktel.id'), nullable=False)

    stara_cena = db.Column(db.Float, nullable=False)
    nova_cena = db.Column(db.Float, nullable=False)
    razlog = db.Column(db.String(100), nullable=True)

    vremenska_oznaka = db.Column(db.DateTime, default=datetime.utcnow)


# --- 4. Logika za Azuriranje Cena (Berza) ---

def azuriraj_cene_koktela(aplikacija):
    # Ovu funkciju APScheduler pokrece automatski svakih 30 sekundi
    with aplikacija.app_context():

        # 1. Definisemo vremenski prozor (poslednjih 30 sekundi)
        vremenski_prozor = datetime.utcnow() - timedelta(seconds=30) # IZMENA: 30 sekundi

        # 2. Brojimo ukupnu kolicinu prodatu po koktelu u tom periodu
        podaci_o_prodaji = db.session.query(
            Transakcija.koktel_id,
            func.sum(Transakcija.kolicina).label('ukupno_prodato')
        ).filter(
            Transakcija.vremenska_oznaka >= vremenski_prozor
        ).group_by(Transakcija.koktel_id).all()

        # Mapiramo rezultate za lakse citanje
        mapa_prodaje = {item.koktel_id: item.ukupno_prodato for item in podaci_o_prodaji}

        # 3. Iteriramo kroz sve koktele i primenjujemo procentualna pravila
        svi_kokteli = Koktel.query.all()

        for koktel in svi_kokteli:
            prodato = mapa_prodaje.get(koktel.id, 0)  # 0 ako nista nije prodato

            stara_cena = koktel.trenutna_cena

            if prodato > 0:
                # Pravilo: Za svaku jedinicu raste za 1%
                faktor_povecanja = 1 + (prodato * 0.01)
                nova_cena = stara_cena * faktor_povecanja
            else:
                # Pravilo: Opadanje za 2% od prethodne cene
                faktor_smanjenja = 0.98
                nova_cena = stara_cena * faktor_smanjenja

            # 4. Postavljanje GORNJEG i DONJEG limita cene
            nova_cena = max(koktel.minimalna_cena, min(nova_cena, koktel.maksimalna_cena))

            # 5. Belezenje promene u tabeli IstorijaCena
            if round(nova_cena, 2) != round(stara_cena, 2):
                istorija = IstorijaCena(
                    koktel_id=koktel.id,
                    stara_cena=stara_cena,
                    nova_cena=nova_cena,
                    razlog=f'{prodato} prodato (promena: {(nova_cena - stara_cena) / stara_cena * 100:.2f}%)'
                )
                db.session.add(istorija)

            # 6. Azuriranje Koktel tabele
            koktel.prethodna_cena = stara_cena
            koktel.trenutna_cena = round(nova_cena, 2)

        db.session.commit()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Cene azurirane.")

## --- 3. Rute Aplikacije ---

def registruj_rute(aplikacija):

    # RUTA 1: Prikaz TV Ekrana (sluzi HTML)
    @aplikacija.route('/tv')
    def tv_ekran():
        # Ova ruta samo renderuje HTML fajl koji ce JS-om povlaciti cene
        return render_template('tv_ekran.html')

    # RUTA 2: API ruta za TV Ekran (sluzi JSON podatke)
    @aplikacija.route('/api/cene_uzivo')
    def api_cene_uzivo():
        # Preuzmi sve koktele
        svi_kokteli = Koktel.query.all()

        # Konvertuj objekte u listu recnika (JSON format)
        lista_cena = []
        for koktel in svi_kokteli:
            # Izracunaj smer promene cene
            promena_smer = 0
            if koktel.trenutna_cena > koktel.prethodna_cena:
                promena_smer = 1
            elif koktel.trenutna_cena < koktel.prethodna_cena:
                promena_smer = -1

            lista_cena.append({
                'id': koktel.id,
                'naziv': koktel.naziv,
                'cena': round(koktel.trenutna_cena, 2),
                'smer': promena_smer
            })

        return jsonify(lista_cena)

     # RUTA 3: PREGLED TRANSAKCIJA (ANALITIKA)
    @aplikacija.route('/transakcije')
    def pregled_transakcija():
            # Preuzima 50 najnovijih narudzbi, sortirane po vremenu
            sve_transakcije = Transakcija.query.order_by(Transakcija.vremenska_oznaka.desc()).limit(50).all()

            # Prikazuje podatke u HTML fajlu
            return render_template('pregled_transakcija.html', transakcije=sve_transakcije)

    # RUTA 4: Unos narudzbe (Barmen)
    @aplikacija.route('/unos_narudzbe', methods=['GET', 'POST'])
    def unos_narudzbe():
        # Preuzmi sve koktele iz baze da bi ih prikazali u formi
        svi_kokteli = Koktel.query.all()

        if request.method == 'POST':
            # 1. Prikupljanje podataka iz forme
            koktel_id = request.form.get('koktel_id')
            kolicina_str = request.form.get('kolicina')
            broj_stola = request.form.get('broj_stola')

            # Konverzija kolicine u broj (integer) i osnovna provera
            try:
                kolicina = int(kolicina_str)
                if kolicina <= 0 or not koktel_id or not broj_stola:
                    return redirect(url_for('unos_narudzbe'))
            except ValueError:
                return redirect(url_for('unos_narudzbe'))

            # 2. Preuzimanje trenutne cene koktela
            odabrani_koktel = Koktel.query.get(koktel_id)

            if odabrani_koktel:
                # 3. Kreiranje novog zapisa u tabeli Transakcija
                nova_transakcija = Transakcija(
                    koktel_id=odabrani_koktel.id,
                    kolicina=kolicina,
                    broj_stola=broj_stola,
                    cena_pri_narudzbi=odabrani_koktel.trenutna_cena,  # Belezenje trenutne cene!
                    vremenska_oznaka=datetime.utcnow()
                )
                db.session.add(nova_transakcija)
                db.session.commit()

                return redirect(url_for('unos_narudzbe'))

        # Prikazi HTML formu (unos_narudzbe.html)
        return render_template('unos_narudzbe.html', kokteli=svi_kokteli)

# --- 5. Pokretanje Aplikacije i Inicijalizacija Baze (MODIFIKOVANO) ---
if __name__ == '__main__':
    # 1. Kreiranje aplikacije
    aplikacija = kreiraj_aplikaciju()

    # 2. Povezivanje ruta sa aplikacijom
    registruj_rute(aplikacija)

    # 3. Kreiranje tabela i dodavanje početnih podataka unutar konteksta aplikacije
    with aplikacija.app_context():
        # Kreira tabele (Koktel, Transakcija, IstorijaCena) u fajlu berza_koktela.db
        db.create_all()

        # Dodavanje početnih koktela ako baza ne sadrži nijedan (Ostaje isto)
        if not Koktel.query.first():
            db.session.add_all([
                Koktel(
                    naziv='Margarita',
                    bazna_cena=10.00,
                    trenutna_cena=10.00,
                    prethodna_cena=10.00,
                    minimalna_cena=8.00,
                    maksimalna_cena=15.00
                ),
                Koktel(
                    naziv='Mojito',
                    bazna_cena=9.50,
                    trenutna_cena=9.50,
                    prethodna_cena=9.50,
                    minimalna_cena=7.50,
                    maksimalna_cena=14.00
                ),
                Koktel(
                    naziv='Old Fashioned',
                    bazna_cena=12.00,
                    trenutna_cena=12.00,
                    prethodna_cena=12.00,
                    minimalna_cena=10.00,
                    maksimalna_cena=18.00
                )
            ])
            db.session.commit()
            print("Pocetni kokteli dodati u bazu podataka.")

    # 4. STARTOVANJE SCHEDULERA
    scheduler.add_job(
        id='AzuiranjeCenaJob',
        func=azuriraj_cene_koktela,
        args=[aplikacija],  # Prosledjujemo aplikaciju funkciji
        trigger='interval',
        seconds=30,  # IZMENA: Pokrece se svakih 30 sekundi
        max_instances=1,
        coalesce=True
    )
    scheduler.start()

    # 5. Pokretanje servera (OBAVEZNO: use_reloader=False)
    aplikacija.run(debug=True, use_reloader=False)