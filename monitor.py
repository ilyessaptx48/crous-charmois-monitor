import os
import re
import json
import smtplib
import requests

from bs4 import BeautifulSoup
from email.message import EmailMessage
from urllib.parse import urljoin

URL = (
    "https://trouverunlogement.lescrous.fr/tools/48/search"
    "?bounds=6.134292_48.7092349_6.2126188_48.666906"
    "&locationName=Nancy+%2854000%29"
)

STATE_FILE = "state.json"
DEBUG_FILE = "debug_page.html"
TARGET = "CHARMOIS"

# Partie de l'URL qui identifie un lien d'annonce.
# Vérifie-la en copiant le lien d'une annonce dans ton navigateur.
LINK_FILTER = "/accommodations/"


def normalize(text):
    return " ".join(text.upper().split())


def get_rooms():
    response = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30
    )
    response.raise_for_status()

    # Le serveur n'indique pas l'encodage : sans cette ligne, requests
    # décode en latin-1 et "m²" / "€" deviennent illisibles.
    response.encoding = "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")
    rooms = {}

    valid_cards = 0
    charmois_found = 0

    for link in soup.find_all("a", href=True):
        # On ignore les liens qui ne sont pas des annonces
        if LINK_FILTER not in link["href"]:
            continue

        card_text = ""

        # Chercher la plus petite carte contenant
        # une surface et un prix.
        for parent in link.parents:
            if parent.name not in ("div", "li", "article"):
                continue

            text = " ".join(
                parent.get_text(" ", strip=True).split()
            )

            has_surface = re.search(
                r"\d+(?:[,.]\d+)?\s*m(?:²|2)",
                text,
                re.I
            )

            has_price = re.search(
                r"\d[\d\s]*[,.]\d{2}\s*€",
                text
            )

            if has_surface and has_price:
                card_text = text
                break

        if not card_text:
            continue

        valid_cards += 1
        text = normalize(card_text)

        if TARGET not in text:
            continue

        charmois_found += 1

        if "INDIVIDUEL" not in text:
            continue

        surface = re.search(
            r"(\d+(?:[,.]\d+)?)\s*m(?:²|2)",
            card_text,
            re.I
        )

        price = re.search(
            r"(\d[\d\s]*[,.]\d{2})\s*€",
            card_text
        )

        if not surface or not price:
            continue

        room_url = urljoin(URL, link["href"])

        rooms[room_url] = {
            "id": room_url,
            "name": "CU DU CHARMOIS",
            "surface": surface.group(1) + " m²",
            "price": price.group(1).replace(" ", "") + " €",
            "url": room_url
        }

    empty_messages = [
        "Aucun logement",
        "Aucun résultat",
        "Aucune offre"
    ]

    page_is_valid = (
        valid_cards > 0
        or any(msg.lower() in response.text.lower()
               for msg in empty_messages)
    )

    print("Cartes détectées :", valid_cards)
    print("Mentions Charmois :", charmois_found)
    print("Chambres individuelles :", len(rooms))

    # Si rien n'est reconnu, on sauvegarde la page pour l'inspecter
    if valid_cards == 0:
        with open(DEBUG_FILE, "w", encoding="utf-8") as file:
            file.write(response.text)
        print("Page sauvegardée dans", DEBUG_FILE)

    return list(rooms.values()), page_is_valid


def send_email(room):
    sender = os.environ.get("EMAIL_ADDRESS")
    password = os.environ.get("EMAIL_APP_PASSWORD")
    recipient = os.environ.get("TO_EMAIL")

    body = f"""
Nouvelle annonce détectée !

Résidence : {room['name']}
Type : Individuel
Surface : {room['surface']}
Loyer : {room['price']}

Lien :
{room['url']}
"""

    # Mode test local : pas d'identifiants -> on affiche seulement
    if not (sender and password and recipient):
        print("[TEST - email non envoyé]")
        print(body)
        return

    message = EmailMessage()
    message["Subject"] = "Nouvelle chambre CROUS - Les Charmois"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(message)


def save_state(ids):
    with open(STATE_FILE, "w") as file:
        json.dump(sorted(ids), file, indent=2)


def main():
    rooms, page_is_valid = get_rooms()

    if not page_is_valid:
        raise RuntimeError(
            "Page non reconnue. État précédent conservé."
        )

    current_ids = {room["id"] for room in rooms}

    if not os.path.exists(STATE_FILE):
        save_state(current_ids)
        print("Initialisation : annonces existantes enregistrées.")
        return

    with open(STATE_FILE, "r") as file:
        known_ids = set(json.load(file))

    new_rooms = [
        room for room in rooms
        if room["id"] not in known_ids
    ]

    for room in new_rooms:
        send_email(room)
        print("Email traité :", room["url"])

    # On conserve uniquement les annonces actuellement présentes.
    # Une annonce qui disparaît puis revient sera détectée.
    save_state(current_ids)

    print("Vérification terminée.")
    print("Nouvelles annonces :", len(new_rooms))


if __name__ == "__main__":
    main()
