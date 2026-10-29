"""
Linha de comando (para você, que é de T.I.). Quem não é usa app.py / BuscaVagas.exe.

    python main.py                # busca + filtro + banco + planilha
    python main.py --only-export  # só relê as marcações e regera a planilha
    python main.py --email        # também envia e-mail com as vagas novas
    python main.py --days 14      # muda a janela de dias
"""
import argparse
import logging

import config
import database
import export_xlsx
import pipeline


def main():
    parser = argparse.ArgumentParser(description="Busca de vagas")
    parser.add_argument("--only-export", action="store_true", help="não busca; só regera a planilha")
    parser.add_argument("--email", action="store_true", help="envia e-mail com as vagas novas")
    parser.add_argument("--days", type=int, help="sobrescreve 'dias' do filtros.json")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(config.LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )

    filters = config.load_filters()
    if args.days:
        filters["dias"] = args.days

    if args.only_export:
        database.init_db()
        print("Planilha:", export_xlsx.sync_spreadsheet(days=int(filters["dias"])))
    else:
        result = pipeline.run_search(filters, send_email=args.email)
        print("Planilha:", result["planilha"])


if __name__ == "__main__":
    main()
