from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Meta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="leser")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    theme: Mapped[str | None] = mapped_column(String(10), default="hell")  # hell | dunkel | auto
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    kundennr: Mapped[str | None] = mapped_column(String(50))
    ansprechpartner: Mapped[str | None] = mapped_column(String(150))
    telefon: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(150))
    notiz: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # UGL-Schnittstelle des Lieferanten (frei konfigurierbar)
    ugl_verfahren: Mapped[str | None] = mapped_column(String(20))
    ugl_pfad: Mapped[str | None] = mapped_column(String(500))  # veraltet, ab 0.2 ersetzt
    ugl_server: Mapped[str | None] = mapped_column(String(255))
    ugl_port: Mapped[str | None] = mapped_column(String(10))
    ugl_pfad_eingang: Mapped[str | None] = mapped_column(String(500))
    ugl_pfad_ausgang: Mapped[str | None] = mapped_column(String(500))
    ugl_pfad_zugferd: Mapped[str | None] = mapped_column(String(500))
    ugl_format: Mapped[str | None] = mapped_column(String(80))
    ugl_benutzer: Mapped[str | None] = mapped_column(String(100))
    ugl_passwort_enc: Mapped[str | None] = mapped_column(Text)
    ugl_notiz: Mapped[str | None] = mapped_column(Text)
    # IDS-Connect (Shop-Schnittstelle, Warenkorb aus dem Großhändler-Shop übernehmen)
    ids_url: Mapped[str | None] = mapped_column(String(500))
    ids_kndnr: Mapped[str | None] = mapped_column(String(50))
    ids_benutzer: Mapped[str | None] = mapped_column(String(100))
    ids_passwort_enc: Mapped[str | None] = mapped_column(Text)
    ids_version: Mapped[str | None] = mapped_column(String(10), default="2.5")
    ids_preis_modus: Mapped[str | None] = mapped_column(String(10), default="gesamt")  # gesamt | einzel
    ids_aufruf: Mapped[str | None] = mapped_column(String(10), default="post")  # post (Formular) | get (Adresszeile)
    # Abruf der UGL-Dateien (FTP/FTPS/Ordner)
    ugl_auto_min: Mapped[int | None] = mapped_column(Integer)          # automatisch alle n Minuten, leer/0 = aus
    ugl_letzter_abruf: Mapped[datetime | None] = mapped_column(DateTime)
    ugl_abruf_status: Mapped[str | None] = mapped_column(String(300))
    ugl_tls_pruefen: Mapped[bool | None] = mapped_column(Boolean, default=True)  # FTPS: Zertifikat prüfen
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))  # optional: Verknüpfung zu Kontakt
    version: Mapped[int] = mapped_column(Integer, default=1)
    contact: Mapped["Contact | None"] = relationship()


class SupplierFile(Base):
    """Eine vom Lieferanten abgerufene Datei (z. B. UGL aus dem Ausgang-Ordner). Der Inhalt liegt in einkauf-data/lieferantendateien/."""
    __tablename__ = "supplier_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    name: Mapped[str] = mapped_column(String(120))
    pfad: Mapped[str] = mapped_column(String(300))          # relativ zu einkauf-data
    groesse: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    abgerufen_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(20), default="neu")   # neu | verarbeitet | ignoriert | fehler
    belegnr: Mapped[str | None] = mapped_column(String(30))
    belegart: Mapped[str | None] = mapped_column(String(10))
    kennung: Mapped[str | None] = mapped_column(String(10))
    datei_datum: Mapped[date | None] = mapped_column(Date)
    positionen: Mapped[int | None] = mapped_column(Integer)
    hinweis: Mapped[str | None] = mapped_column(String(300))
    bestell_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    aktion: Mapped[str | None] = mapped_column(String(20))
    verarbeitet_am: Mapped[datetime | None] = mapped_column(DateTime)
    supplier: Mapped[Supplier] = relationship()


class Setting(Base):
    """Einfache Einstellungen (Schlüssel/Wert), z. B. für die Lexoffice-Schnittstelle."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class Contact(Base):
    """Kontakt (Kunde und/oder Lieferant). Feldsatz nach den Kontakten von Lexoffice/Lexware Office,
    damit die spätere Synchronisierung 1:1 abbilden kann. Pro Liste (Adresse, E-Mail, Telefon)
    wird der erste Eintrag übernommen, Ansprechpartner stehen in eigener Tabelle."""
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lexoffice_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    lexoffice_version: Mapped[int | None] = mapped_column(Integer)
    quelle: Mapped[str] = mapped_column(String(20), default="manuell")  # manuell | lexoffice
    typ: Mapped[str] = mapped_column(String(10), default="firma")  # firma | person
    ist_kunde: Mapped[bool] = mapped_column(Boolean, default=True)
    ist_lieferant: Mapped[bool] = mapped_column(Boolean, default=False)
    kunde_nr: Mapped[str | None] = mapped_column(String(20))
    lieferant_nr: Mapped[str | None] = mapped_column(String(20))
    firma: Mapped[str | None] = mapped_column(String(200))
    steuernummer: Mapped[str | None] = mapped_column(String(50))
    ust_idnr: Mapped[str | None] = mapped_column(String(30))
    steuerfrei: Mapped[bool] = mapped_column(Boolean, default=False)
    anrede: Mapped[str | None] = mapped_column(String(50))
    vorname: Mapped[str | None] = mapped_column(String(100))
    nachname: Mapped[str | None] = mapped_column(String(100))
    re_zusatz: Mapped[str | None] = mapped_column(String(200))
    re_strasse: Mapped[str | None] = mapped_column(String(200))
    re_plz: Mapped[str | None] = mapped_column(String(20))
    re_ort: Mapped[str | None] = mapped_column(String(100))
    re_land: Mapped[str | None] = mapped_column(String(5))
    li_zusatz: Mapped[str | None] = mapped_column(String(200))
    li_strasse: Mapped[str | None] = mapped_column(String(200))
    li_plz: Mapped[str | None] = mapped_column(String(20))
    li_ort: Mapped[str | None] = mapped_column(String(100))
    li_land: Mapped[str | None] = mapped_column(String(5))
    email_geschaeft: Mapped[str | None] = mapped_column(String(150))
    email_buero: Mapped[str | None] = mapped_column(String(150))
    email_privat: Mapped[str | None] = mapped_column(String(150))
    email_sonstige: Mapped[str | None] = mapped_column(String(150))
    tel_geschaeft: Mapped[str | None] = mapped_column(String(50))
    tel_buero: Mapped[str | None] = mapped_column(String(50))
    tel_mobil: Mapped[str | None] = mapped_column(String(50))
    tel_privat: Mapped[str | None] = mapped_column(String(50))
    tel_fax: Mapped[str | None] = mapped_column(String(50))
    tel_sonstige: Mapped[str | None] = mapped_column(String(50))
    leitweg_id: Mapped[str | None] = mapped_column(String(50))  # xRechnung: buyerReference
    lieferantennr_beim_kunden: Mapped[str | None] = mapped_column(String(50))  # xRechnung
    notiz: Mapped[str | None] = mapped_column(Text)
    archiviert: Mapped[bool] = mapped_column(Boolean, default=False)
    letzter_sync: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    personen: Mapped[list["ContactPerson"]] = relationship(
        back_populates="contact", order_by="ContactPerson.id", cascade="all, delete-orphan")

    @property
    def name(self):
        if self.typ == "person":
            return " ".join(x for x in (self.vorname, self.nachname) if x) or (self.firma or "")
        return self.firma or " ".join(x for x in (self.vorname, self.nachname) if x)

    @property
    def ort(self):
        return self.re_ort or self.li_ort or ""

    @property
    def telefon(self):
        return self.tel_geschaeft or self.tel_buero or self.tel_mobil or self.tel_privat or self.tel_sonstige or ""

    @property
    def email(self):
        return self.email_geschaeft or self.email_buero or self.email_privat or self.email_sonstige or ""

    @property
    def nummern(self):
        t = []
        if self.kunde_nr:
            t.append(f"Kd {self.kunde_nr}")
        if self.lieferant_nr:
            t.append(f"Lief {self.lieferant_nr}")
        return " · ".join(t)


class ContactPerson(Base):
    __tablename__ = "contact_persons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    anrede: Mapped[str | None] = mapped_column(String(50))
    vorname: Mapped[str | None] = mapped_column(String(100))
    nachname: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(150))
    telefon: Mapped[str | None] = mapped_column(String(50))
    primaer: Mapped[bool] = mapped_column(Boolean, default=False)
    contact: Mapped[Contact] = relationship(back_populates="personen")


class NumberRange(Base):
    """Nummernkreis: Präfix, Trenner, optional Jahr, Stellenzahl und nächster Zähler."""
    __tablename__ = "number_ranges"
    key: Mapped[str] = mapped_column(String(30), primary_key=True)  # projekt | bestellung
    # Muster (ab Schema 6): z. B. P-YYYY-XXXX. Die Spalten praefix/trenner/mit_jahr/stellen/jahr stammen aus Schema 5,
    # werden nicht mehr gelesen und bleiben nur, damit bestehende Datenbanken (NOT NULL) weiter befüllbar sind.
    muster: Mapped[str | None] = mapped_column(String(60))
    reset: Mapped[str | None] = mapped_column(String(10), default="auto")  # auto | nie | jahr | monat | tag
    periode: Mapped[str | None] = mapped_column(String(12))  # Jahr/Monat/Tag, für den der Zähler gilt
    praefix: Mapped[str] = mapped_column(String(20), default="")
    trenner: Mapped[str] = mapped_column(String(5), default="-")
    mit_jahr: Mapped[bool] = mapped_column(Boolean, default=True)
    stellen: Mapped[int] = mapped_column(Integer, default=4)
    start: Mapped[int] = mapped_column(Integer, default=1)  # Zähler nach Jahreswechsel
    naechste: Mapped[int] = mapped_column(Integer, default=1)
    jahr: Mapped[int | None] = mapped_column(Integer)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nummer: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kunde: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="aktiv")
    materialbudget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    budget_modus: Mapped[str | None] = mapped_column(String(20), default="manuell")  # manuell | warensumme | faktor
    budget_faktor: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), default=Decimal("1.000"))
    notiz: Mapped[str | None] = mapped_column(Text)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))  # optional: Kunde aus den Kontakten
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="project")
    contact: Mapped["Contact | None"] = relationship()
    lex_documents: Mapped[list["LexDocument"]] = relationship(back_populates="project", order_by="LexDocument.datum.desc(), LexDocument.id.desc()")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    bestelldatum: Mapped[date] = mapped_column(Date)
    bestellnr: Mapped[str | None] = mapped_column(String(50))
    ab_nr: Mapped[str | None] = mapped_column(String(50))
    wunschtermin: Mapped[date | None] = mapped_column(Date)
    notiz: Mapped[str | None] = mapped_column(Text)
    # neu -> bestellt -> teilgeliefert -> komplett -> abgeschlossen (bezahlt)
    status: Mapped[str] = mapped_column(String(20), default="neu")
    bestellt_am: Mapped[date | None] = mapped_column(Date)
    bezahlt_am: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    supplier: Mapped[Supplier] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", order_by="OrderItem.id", cascade="all, delete-orphan"
    )
    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="order", order_by="Delivery.id", cascade="all, delete-orphan"
    )

    def status_aktualisieren(self):
        """Leitet Teillieferung/Komplett aus den gebuchten Wareneingängen ab."""
        if self.status == "abgeschlossen":
            return
        aktiv = [i for i in self.items if not i.storniert]
        if not aktiv:
            return
        if all(i.rest <= 0 for i in aktiv):
            self.status = "komplett"
        elif any(i.geliefert > 0 for i in aktiv):
            self.status = "teilgeliefert"
        elif self.status in ("komplett", "teilgeliefert"):
            self.status = "bestellt"

    @property
    def offen(self):
        return any(i.rest > 0 for i in self.items if not i.storniert)

    @property
    def summe(self):
        return sum((i.menge * i.preis for i in self.items if not i.storniert and i.preis is not None), Decimal(0))


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    artikelnr: Mapped[str | None] = mapped_column(String(100))
    bezeichnung: Mapped[str] = mapped_column(String(300))
    menge: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    einheit: Mapped[str | None] = mapped_column(String(20))
    preis: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    erw_lieferdatum: Mapped[date | None] = mapped_column(Date)
    storniert: Mapped[bool] = mapped_column(Boolean, default=False)
    kommission: Mapped[str | None] = mapped_column(String(300))  # z. B. "kirsch 2x / 1x Lager"
    hinweis: Mapped[str | None] = mapped_column(String(300))  # z. B. "beim Lieferanten in Rückstand"

    order: Mapped[Order] = relationship(back_populates="items")
    project: Mapped[Project | None] = relationship(back_populates="items")
    delivery_items: Mapped[list["DeliveryItem"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    @property
    def geliefert(self):
        return sum((d.menge for d in self.delivery_items), Decimal(0))

    @property
    def rest(self):
        return max(self.menge - self.geliefert, Decimal(0))

    @property
    def status(self):
        if self.storniert:
            return "Storniert"
        if self.rest <= 0:
            return "Geliefert"
        if self.geliefert > 0:
            return "Teilgeliefert"
        return "Offen"

    @property
    def faellig(self):
        """'ueberfaellig', 'bald' oder ''. Nur für offene Positionen."""
        if self.storniert or self.rest <= 0 or not self.erw_lieferdatum:
            return ""
        heute = date.today()
        if self.erw_lieferdatum < heute:
            return "ueberfaellig"
        if self.erw_lieferdatum <= heute + timedelta(days=3):
            return "bald"
        return ""


class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    lieferschein_nr: Mapped[str | None] = mapped_column(String(80))
    datum: Mapped[date] = mapped_column(Date)
    notiz: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    order: Mapped[Order] = relationship(back_populates="deliveries")
    items: Mapped[list["DeliveryItem"]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan"
    )


class DeliveryItem(Base):
    __tablename__ = "delivery_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"))
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id"))
    menge: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    delivery: Mapped[Delivery] = relationship(back_populates="items")
    item: Mapped[OrderItem] = relationship(back_populates="delivery_items")


class LexDocument(Base):
    """Aus Lexoffice übernommener Beleg (Angebot, Auftrag/AB oder Rechnung), nur lesend."""
    __tablename__ = "lex_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lexoffice_id: Mapped[str] = mapped_column(String(40), unique=True)
    lexoffice_version: Mapped[int | None] = mapped_column(Integer)
    typ: Mapped[str] = mapped_column(String(20))                     # angebot | auftrag | rechnung
    nummer: Mapped[str | None] = mapped_column(String(60))
    datum: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(30))
    contact_lex_id: Mapped[str | None] = mapped_column(String(40))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    kunde_name: Mapped[str | None] = mapped_column(String(200))
    titel: Mapped[str | None] = mapped_column(String(300))
    netto: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    brutto: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    waehrung: Mapped[str | None] = mapped_column(String(10), default="EUR")
    archiviert: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at_lex: Mapped[str | None] = mapped_column(String(40))
    letzter_sync: Mapped[datetime | None] = mapped_column(DateTime)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)

    project: Mapped["Project | None"] = relationship(back_populates="lex_documents")
    contact: Mapped["Contact | None"] = relationship()
    items: Mapped[list["LexDocumentItem"]] = relationship(
        back_populates="document", order_by="LexDocumentItem.position, LexDocumentItem.id",
        cascade="all, delete-orphan",
    )

    @property
    def materialwert(self):
        return sum((i.materialwert for i in self.items), Decimal("0.00"))

    @property
    def unklar_anzahl(self):
        return sum(1 for i in self.items if i.ist_unklar)


class LexDocumentItem(Base):
    """Position eines Lexoffice-Belegs inkl. Kostenart für die Materialbudget-Berechnung."""
    __tablename__ = "lex_document_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("lex_documents.id"))
    position: Mapped[int] = mapped_column(Integer, default=1)
    lex_artikel_id: Mapped[str | None] = mapped_column(String(40))
    lex_typ: Mapped[str | None] = mapped_column(String(20))         # material | service | custom | text
    bezeichnung: Mapped[str] = mapped_column(String(300))
    beschreibung: Mapped[str | None] = mapped_column(Text)
    menge: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    einheit: Mapped[str | None] = mapped_column(String(30))
    einzelpreis_netto: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    rabatt_prozent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    gesamt_netto: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    kostenart: Mapped[str | None] = mapped_column(String(20))       # None (unklar) | material | pauschale | fremdleistung | arbeit
    materialanteil: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=Decimal("100.00"))

    document: Mapped[LexDocument] = relationship(back_populates="items")

    @property
    def ist_unklar(self):
        if self.lex_typ == "text":
            return False
        if self.gesamt_netto is None:
            return False
        return self.kostenart is None

    @property
    def materialwert(self):
        if self.gesamt_netto is None or self.kostenart is None:
            return Decimal("0.00")
        if self.kostenart == "material":
            return self.gesamt_netto
        if self.kostenart == "pauschale":
            anteil = self.materialanteil if self.materialanteil is not None else Decimal("0")
            return (self.gesamt_netto * anteil / Decimal("100")).quantize(Decimal("0.01"))
        return Decimal("0.00")


class LexArticleRule(Base):
    """Gemerkte Kostenart pro Lexoffice-Artikel (ID oder Bezeichnung)."""
    __tablename__ = "lex_article_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schluessel: Mapped[str] = mapped_column(String(300), unique=True)
    lex_artikel_id: Mapped[str | None] = mapped_column(String(40))
    bezeichnung: Mapped[str | None] = mapped_column(String(300))
    kostenart: Mapped[str] = mapped_column(String(20))              # material | pauschale | fremdleistung | arbeit
    materialanteil: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("100.00"))


class EditLock(Base):
    """Sperre bei gleichzeitigem Bearbeiten (Optimistic + Pessimistic Lock)."""
    __tablename__ = "edit_locks"
    __table_args__ = (UniqueConstraint("obj_typ", "obj_id", name="uq_edit_lock_obj"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    obj_typ: Mapped[str] = mapped_column(String(30))                # bestellung | projekt | kontakt | lieferant | lex_beleg
    obj_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    username: Mapped[str] = mapped_column(String(80))
    seit: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    ablauf: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    """Änderungsprotokoll für wichtige Vorgänge in BeLiKo."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zeit: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    username: Mapped[str | None] = mapped_column(String(80))
    aktion: Mapped[str] = mapped_column(String(40))                 # angelegt | geaendert | geloescht | gebucht | sync | sicherung
    obj_typ: Mapped[str] = mapped_column(String(30))
    obj_id: Mapped[int | None] = mapped_column(Integer)
    obj_name: Mapped[str | None] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(String(500))


class Article(Base):
    """Artikelstamm (z. B. aus Datanorm-Import)."""
    __tablename__ = "articles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artikelnr: Mapped[str] = mapped_column(String(100), unique=True)
    bezeichnung: Mapped[str] = mapped_column(String(300))
    kurztext2: Mapped[str | None] = mapped_column(String(300))
    einheit: Mapped[str | None] = mapped_column(String(20))
    listenpreis: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    rabattgruppe: Mapped[str | None] = mapped_column(String(30))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    quelle: Mapped[str] = mapped_column(String(20), default="datanorm")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    supplier: Mapped["Supplier | None"] = relationship()


class SupplierInvoice(Base):
    """Eingelesene Lieferantenrechnung (z. B. ZUGFeRD / Factur-X) für den Rechnungsabgleich."""
    __tablename__ = "supplier_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    rechnungsnr: Mapped[str] = mapped_column(String(80))
    datum: Mapped[date | None] = mapped_column(Date)
    lieferant_name: Mapped[str | None] = mapped_column(String(200))
    netto: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    brutto: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    waehrung: Mapped[str | None] = mapped_column(String(10), default="EUR")
    dateiname: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="offen")  # offen | geprueft | abweichung
    notiz: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    supplier: Mapped["Supplier | None"] = relationship()
    order: Mapped["Order | None"] = relationship()
