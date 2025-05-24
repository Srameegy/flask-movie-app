import os
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)

# Load environment variables
load_dotenv()
api_key = os.getenv("TMDB_API_KEY")

# =========================
# Genre Cache
# =========================
genre_cache = {}

def get_genres():
    """Fetch genre list from TMDB and cache it."""
    if not genre_cache:
        url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={api_key}&language=en-US"
        response = requests.get(url)
        data = response.json()
        genre_cache.update({g['id']: g['name'] for g in data['genres']})
    return genre_cache

# =========================
# TMDB Streaming Providers (Saudi Arabia)
# =========================
def get_streaming_providers(movie_id, movie_title):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/watch/providers?api_key={api_key}"
    response = requests.get(url)
    if response.status_code != 200:
        return []

    data = response.json().get("results", {}).get("SA")
    if not data or "flatrate" not in data:
        return []

    # Predefined search links for popular providers
    search_links = {
        "Netflix": f"https://www.netflix.com/search?q={movie_title}",
        "Shahid VIP": f"https://shahid.mbc.net/en/search?q={movie_title}",
        "OSN": f"https://stream.osn.com/en/search?q={movie_title}",
        "Disney Plus": f"https://www.disneyplus.com/search/{movie_title}",
        "Amazon Prime Video": f"https://www.amazon.com/s?k={movie_title}",
        "Apple TV": f"https://tv.apple.com/search/{movie_title}",
    }

    # Build final list with fallback to Google search
    streaming_list = []
    for p in data["flatrate"]:
        provider_name = p["provider_name"]
        logo_url = f"https://image.tmdb.org/t/p/w92{p['logo_path']}"

        # Use predefined link or fallback to Google search
        link = search_links.get(
            provider_name,
            f"https://www.google.com/search?q={movie_title.replace(' ', '+')}+{provider_name.replace(' ', '+')}+stream"
        )

        streaming_list.append({
            "name": provider_name,
            "logo_url": logo_url,
            "link": link
        })

    return streaming_list

# =========================
# Home Page
# =========================
@app.route('/')
def home():
    sort_by = request.args.get('sort_by', 'date')
    genre_filter = request.args.get('genre')
    genres = get_genres()

    movies = []
    for page in range(1, 3):
        url = f"https://api.themoviedb.org/3/movie/now_playing?api_key={api_key}&language=en-US&page={page}"
        response = requests.get(url)
        data = response.json()
        movies.extend(data["results"])

    if genre_filter:
        try:
            genre_filter = int(genre_filter)
            movies = [m for m in movies if genre_filter in m.get('genre_ids', [])]
        except ValueError:
            pass

    if sort_by == 'rating':
        movies.sort(key=lambda m: m['vote_average'], reverse=True)
    else:
        movies.sort(key=lambda m: datetime.strptime(m['release_date'], "%Y-%m-%d"), reverse=True)

    return render_template("home.html",
                           movies=movies,
                           sort_by=sort_by,
                           genres=genres,
                           genre_filter=genre_filter)

# =========================
# Movie Detail Page
# =========================
@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    # Fetch movie details
    movie_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={api_key}&language=en-US"
    movie = requests.get(movie_url).json()

    # Fetch trailer
    videos_url = f"https://api.themoviedb.org/3/movie/{movie_id}/videos?api_key={api_key}&language=en-US"
    videos = requests.get(videos_url).json().get("results", [])
    trailer = next((v for v in videos if v["site"] == "YouTube" and v["type"] == "Trailer"), None)
    trailer_key = trailer["key"] if trailer else None

    # Fetch streaming providers
    streaming_links = get_streaming_providers(movie_id, movie["title"])

    # Fetch cast (top 5)
    credits_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits?api_key={api_key}&language=en-US"
    credits = requests.get(credits_url).json()
    cast = credits.get("cast", [])[:5]

    return render_template("movie_detail.html",
                           movie=movie,
                           trailer_key=trailer_key,
                           streaming_links=streaming_links,
                           cast=cast)


# =========================
# Search Page
# =========================
@app.route('/search')
def search():
    query = request.args.get('query', '').strip()
    search_type = request.args.get('type', 'movie')
    sort_by = request.args.get('sort_by', 'date')
    genre_filter = request.args.get('genre')
    selected_actor = request.args.get('actor')
    genres = get_genres()

    if not query:
        return render_template("search.html", query=query, type=search_type, movies=[], people=[], genres=genres,
                               sort_by=sort_by, genre_filter=genre_filter, actors=[], selected_actor=None)

    tmdb_url = f"https://api.themoviedb.org/3/search/{search_type}?api_key={api_key}&language=en-US&query={query}&include_adult=false"
    response = requests.get(tmdb_url)
    data = response.json().get("results", [])

    if search_type == 'person':
        filtered = [p for p in data if query.lower() in p.get("name", "").lower()]
        return render_template("search.html", query=query, type=search_type, people=filtered, movies=[],
                               genres=genres, sort_by=sort_by, genre_filter=genre_filter, actors=[], selected_actor=None)

    # Movie filter by genre
    if genre_filter:
        try:
            genre_filter = int(genre_filter)
            data = [m for m in data if genre_filter in m.get('genre_ids', [])]
        except ValueError:
            pass

    # Sort movies
    if sort_by == 'rating':
        data.sort(key=lambda m: m['vote_average'], reverse=True)
    else:
        data.sort(key=lambda m: datetime.strptime(m['release_date'], "%Y-%m-%d") if m.get('release_date') else datetime.min, reverse=True)

    # ============================
    # NEW: Filter by actor
    # ============================
    actors = []
    if data:
        for movie in data:
            # Fetch cast for each movie (top 3 only for performance)
            movie_id = movie["id"]
            credits_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits?api_key={api_key}"
            credits = requests.get(credits_url).json()
            cast_list = [c["name"] for c in credits.get("cast", [])[:3]]
            movie["cast_names"] = cast_list
            actors.extend(cast_list)

        # Deduplicate actors list
        actors = sorted(set(actors))

        if selected_actor:
            data = [m for m in data if selected_actor in m.get("cast_names", [])]

    return render_template("search.html",
                           query=query,
                           type=search_type,
                           movies=data,
                           people=[],
                           genres=genres,
                           sort_by=sort_by,
                           genre_filter=genre_filter,
                           actors=actors,
                           selected_actor=selected_actor)



@app.route('/autocomplete')
def autocomplete():
    query = request.args.get('query', '')
    search_type = request.args.get('type', 'movie')

    if not query:
        return jsonify([])

    tmdb_url = f"https://api.themoviedb.org/3/search/{search_type}?api_key={api_key}&language=en-US&query={query}&include_adult=false"
    response = requests.get(tmdb_url)
    if response.status_code != 200:
        return jsonify([])

    results = response.json().get('results', [])

    if search_type == 'person':
        # Include ID to redirect to actor's movie list
        suggestions = [{"name": p["name"], "id": p["id"]} for p in results[:8]]
    else:
        suggestions = [{"name": m["title"]} for m in results[:8]]

    return jsonify(suggestions)



@app.route('/person/<int:person_id>')
def person_movies(person_id):
    # Get all movies for a person using TMDB credit endpoint
    url = f"https://api.themoviedb.org/3/person/{person_id}/movie_credits?api_key={api_key}&language=en-US"
    response = requests.get(url)
    credits = response.json()

    person_url = f"https://api.themoviedb.org/3/person/{person_id}?api_key={api_key}"
    person_info = requests.get(person_url).json()
    person_name = person_info.get("name", "Unknown Actor")

    # Only include movies (skip crew, use only cast)
    movies = credits.get("cast", [])
    movies.sort(key=lambda m: m.get('popularity', 0), reverse=True)

    return render_template("search.html", query=person_name, type='person', movies=movies, people=[], genres=get_genres(), sort_by='date', genre_filter=None)





# =========================
# Run App
# =========================
if __name__ == '__main__':
    app.run(debug=True)
