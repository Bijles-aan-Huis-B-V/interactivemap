from flask import Flask, request, render_template_string
import folium

app = Flask(__name__)

html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Map Viewer</title>
    <style>
        #map { height: 500px; margin-top: 20px; }
    </style>
</head>
<body>
    <h3>Enter Latitude and Longitude:</h3>
    <form method="POST" action="/">
        Latitude: <input type="text" name="latitude"><br>
        Longitude: <input type="text" name="longitude"><br><br>
        <input type="submit" value="Submit">
    </form>

    {% if map_html %}
        <h4>Generated Map:</h4>
        <div id="map">{{ map_html|safe }}</div>
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    map_html = None
    if request.method == "POST":
        try:
            lat = float(request.form.get("latitude"))
            lon = float(request.form.get("longitude"))
            
            map_object = folium.Map(location=[lat, lon], zoom_start=12)
            folium.Marker([lat, lon], popup="User Location").add_to(map_object)
            map_html = map_object._repr_html_()
        except (ValueError, TypeError):
            map_html = "<p>Invalid latitude or longitude. Please try again.</p>"
    
    return render_template_string(html_template, map_html=map_html)

if __name__ == "__main__":
    app.run(debug=True)