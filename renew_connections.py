import datetime
import json
import time
import sys
import qrcode
import polars as pl
from go_cardless_client import Client

def get_institution_info(client, inst_id):
    row = client.institutions.filter(pl.col("id") == inst_id)
    if row.height == 0:
        return 730, 90, inst_id
    
    max_days = row.select("transaction_total_days").item(0, 0)
    valid_days = row.select("max_access_valid_for_days").item(0, 0)
    name = row.select("name").item(0, 0)
    
    # Fallback to defaults if None
    if max_days is None:
        max_days = 730
    if valid_days is None:
        valid_days = 90
        
    return max_days, valid_days, name

def main():
    print("Initializing GoCardless Client...")
    client = Client()
    
    target_institutions = ["REVOLUT_REVOGB21", "BARCLAYS_BUKBGB22"]
    active_requisitions = []
    
    print("\nStarting renewal process...")
    for inst_id in target_institutions:
        max_days, valid_days, name = get_institution_info(client, inst_id)
        print(f"\n==================================================")
        print(f"Creating Agreement & Requisition for: {name} ({inst_id})")
        print(f"==================================================")
        
        # 1. Create Agreement
        agreement_payload = {
            "institution_id": inst_id,
            "max_historical_days": max_days,
            "access_valid_for_days": valid_days,
            "access_scope": ["balances", "details", "transactions"]
        }
        agreement = client.post("agreements/enduser/", agreement_payload)
        if not agreement:
            print(f"Failed to create agreement for {name}.")
            sys.exit(1)
            
        agreement_id = agreement["id"]
        print(f"Created Agreement: {agreement_id}")
        
        # 2. Create Requisition
        ref_suffix = datetime.date.today().strftime("%Y_%m")
        friendly_ref = f"{name.split()[0]}_renewed_{ref_suffix}"
        requisition_payload = {
            "institution_id": inst_id,
            "agreement": agreement_id,
            "redirect": "https://google.com",
            "reference": friendly_ref
        }
        requisition = client.post("requisitions/", requisition_payload)
        if not requisition:
            print(f"Failed to create requisition for {name}.")
            sys.exit(1)
            
        req_id = requisition["id"]
        link_url = requisition["link"]
        print(f"Created Requisition: {req_id}")
        print(f"Authorization Link: {link_url}")
        
        # 3. Print QR code
        print("Scan QR code below on mobile to authorize:")
        qr = qrcode.QRCode(box_size=1, border=1)
        qr.add_data(link_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        
        active_requisitions.append({
            "name": name,
            "req_id": req_id,
            "status": "CR",
            "accounts": []
        })

    print(f"\n==================================================")
    print("Requisitions created successfully.")
    print("Please open the links above (or scan the QR codes) to authorize connections in your browser/banking apps.")
    print("Once done, the script will detect the authorization and link automatically.")
    print("==================================================")
    
    # 4. Polling loop
    print("Polling for authorization status... (Press Ctrl+C to abort)")
    try:
        while True:
            all_linked = True
            statuses = []
            
            # Fetch fresh list of requisitions
            reqs_data = client.get("requisitions/")
            if not reqs_data:
                print("Warning: Failed to fetch requisition status from API. Retrying in 5s...")
                time.sleep(5)
                continue
                
            req_map = {r["id"]: r for r in reqs_data.get("results", [])}
            
            for req in active_requisitions:
                # Find matching req in API response
                api_req = req_map.get(req["req_id"])
                if api_req:
                    req["status"] = api_req.get("status", "CR")
                    req["accounts"] = api_req.get("accounts", [])
                
                status_str = f"{req['name']}: {req['status']}"
                if req["status"] == "LN":
                    status_str += f" (Accounts: {', '.join(req['accounts'])})"
                else:
                    all_linked = False
                statuses.append(status_str)
                
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] " + " | ".join(statuses), end="\r")
            
            if all_linked:
                print("\n\nAll accounts successfully linked!")
                for req in active_requisitions:
                    print(f" - {req['name']}: Linked accounts -> {req['accounts']}")
                break
                
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\nPolling aborted by user. Run the script again or check the status later.")

if __name__ == "__main__":
    main()
