import json
from app.main import app

def main():
    print("Generating OpenAPI specification...")
    # Get the automatically generated OpenAPI schema from FastAPI
    openapi_schema = app.openapi()
    
    out_path = "openapi.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2)
        
    print(f"Successfully generated {out_path}")

if __name__ == "__main__":
    main()
