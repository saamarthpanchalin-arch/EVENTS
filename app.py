import os
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from postgrest import APIError
from supabase import Client, create_client

load_dotenv()


def create_app(supabase_client: Client | None = None) -> Flask:
    """Create the unauthenticated event-registration API."""
    app = Flask(__name__)
    client = supabase_client or create_client(
        os.environ["SUPABASE_URL"], os.environ.get("SUPABASE_SECRET_KEY") or os.environ["SUPABASE_PUBLISHABLE_KEY"]
    )

    def error(message: str, status_code: int):
        return jsonify({"error": message}), status_code

    def require_uuid(value, field_name: str):
        if not value:
            return None, error(f"{field_name} is required", 400)
        try:
            return str(UUID(str(value))), None
        except (TypeError, ValueError):
            return None, error(f"{field_name} must be a valid UUID", 400)

    @app.errorhandler(APIError)
    def handle_supabase_error(api_error):
        return error(api_error.message, 502)

    @app.get("/")
    def index():
        return jsonify({"service": "event-api", "authentication": "disabled"})

    @app.get("/api/events")
    def list_events():
        response = client.table("events").select("*").order("title").execute()
        return jsonify(response.data)

    @app.get("/api/events/<event_id>")
    def get_event(event_id: str):
        event_id, validation_error = require_uuid(event_id, "event_id")
        if validation_error:
            return validation_error
        response = client.table("events").select("*").eq("id", event_id).limit(1).execute()
        if not response.data:
            return error("event not found", 404)
        return jsonify(response.data[0])

    @app.post("/api/registrations")
    def create_registration():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("request body must be a JSON object", 400)
        user_id, validation_error = require_uuid(payload.get("user_id"), "user_id")
        if validation_error:
            return validation_error
        event_id, validation_error = require_uuid(payload.get("event_id"), "event_id")
        if validation_error:
            return validation_error

        event_response = client.table("events").select("id,capacity").eq("id", event_id).limit(1).execute()
        if not event_response.data:
            return error("event not found", 404)
        existing_response = client.table("registrations").select("id").eq("user_id", user_id).eq("event_id", event_id).limit(1).execute()
        if existing_response.data:
            return error("user is already registered for this event", 409)

        capacity = event_response.data[0].get("capacity")
        if capacity is not None:
            registration_count = client.table("registrations").select("id", count="exact").eq("event_id", event_id).execute()
            if registration_count.count is not None and registration_count.count >= capacity:
                return error("event is at capacity", 409)

        response = client.table("registrations").insert({"user_id": user_id, "event_id": event_id}).execute()
        return jsonify(response.data[0]), 201

    @app.get("/api/me/registrations")
    def list_user_registrations():
        # Authentication is intentionally deferred. Callers identify the user for now.
        user_id, validation_error = require_uuid(request.args.get("user_id"), "user_id")
        if validation_error:
            return validation_error
        response = client.table("registrations").select("id,user_id,event_id,created_at,events(*)").eq("user_id", user_id).order("created_at", desc=True).execute()
        return jsonify(response.data)

    @app.get("/api/events/<event_id>/registrations")
    def list_event_registrations(event_id: str):
        event_id, validation_error = require_uuid(event_id, "event_id")
        if validation_error:
            return validation_error
        response = client.table("registrations").select("id,user_id,event_id,created_at,users(id,email,role)").eq("event_id", event_id).order("created_at", desc=True).execute()
        return jsonify(response.data)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)

@app.route("/")
def home():
    return jsonify({
        "service": "event-api",
        "status": "running",
        "message": "Event API is operational",
        "endpoints": {
            "events": "/api/events",
            "users": "/api/users",
            "registrations": "/api/registrations"
        }
    }), 200