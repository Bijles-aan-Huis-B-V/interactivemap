from flask import Flask, render_template, request
from datetime import date, datetime
import pandas as pd
import folium

app = Flask(__name__)

def convert_float_list_to_int(float_list):
    int_list = []
    for x in float_list:
      if x == '-Empty-':
        int_list.append(x)
      else: 
        try:
            # Attempt to convert x to float first, then to int
            int_list.append(int(float(x)))  # This will handle float-like strings too
        except (ValueError, TypeError):
            # If there's a conversion error, skip this item
            continue
    return int_list
  
def categorize(value):
    if value < 5.0:
        return 'blue'
    elif 5.0 <= value <= q25:
        return 'red'
    elif value >= q75:
        return 'green'
    else:
        return 'yellow'
        
from math import radians, cos, sin, asin, sqrt

def haversine(lat1, lon1, lat2, lon2):
    # Convert degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371  # Radius of Earth in kilometers
    return c * r

# Load the datasets
Courses = pd.read_csv('Courses.csv')
Tutor = pd.read_csv('Tutor.csv')

#Calculate relations percentile
Quantiles = Tutor[Tutor['lessons_per_relation'] >= 5.0]
q25 = Quantiles['lessons_per_relation'].quantile(0.25)
q75 = Quantiles['lessons_per_relation'].quantile(0.75)

Tutor['quantile_labels'] = Tutor['lessons_per_relation'].apply(categorize)
Tutor['recent_lesson'] = Tutor['recent_lesson'].apply(
    lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S.%f").date() if isinstance(x, str) else None
)

@app.route('/', methods=['GET', 'POST'])
def index():
    # Initialize variables
    filtered_df = Courses.copy()
    temp_df = Tutor[['tutor', 'number_of_relations', 'lessons_per_relation', 'excluded_from_search', 'recent_lesson']]
    filtered_df = pd.merge(filtered_df, temp_df, how = 'left', on = 'tutor')
    countries = Courses['country'].unique().tolist()
    school_levels = school_years = school_types = course_names = availability = tutor_types = excluded = []
    map_html = None
    selected_country = None
    selected_school_levels = selected_school_years = selected_school_types = selected_course_names = selected_availabilities = lessons_per_relation = no_lesson_tutor = selected_tutor_types = selected_excluded = []
    start_date = end_date = None
    df_html = None

    if request.method == 'POST':
        # Handle first form submission for country selection
        selected_country = request.form.get('country')

        # Filter data by the selected country only if one is selected
        if selected_country:
            filtered_df = filtered_df[filtered_df['country'] == selected_country]

        # Extract unique values for dropdowns, replacing NaN with '-Empty-'
            school_levels = filtered_df['school_level'].fillna('-Empty-').unique().tolist()
            school_levels = sorted(school_levels, key=lambda x: (x == '-Empty-', x))
            
            school_years = filtered_df['school_year'].fillna('-Empty-').unique().tolist()
            school_years = sorted(x for x in school_years if isinstance(x, float)) + [x for x in school_years if isinstance(x, str)]
            
            school_types = filtered_df['school_type'].fillna('-Empty-').unique().tolist()
            school_types = sorted(school_types, key=lambda x: (x == '-Empty-', x))
            
            course_names = filtered_df['course_name'].fillna('-Empty-').unique().tolist()
            course_names = sorted(course_names, key=lambda x: (x == '-Empty-', x))
            
            availability = filtered_df['availability'].fillna('-Empty-').unique().tolist()
            
            excluded = filtered_df['excluded_from_search'].fillna('-Empty').unique().tolist()
            
            tutor_types = filtered_df['tutor_category'].fillna('-Empty-').unique().tolist()
            tutor_types = sorted(x for x in tutor_types if isinstance(x, float)) + [x for x in tutor_types if isinstance(x, str)]
            

        # Handle the second form submission for additional filters
            selected_school_levels = request.form.getlist('school_level')  
            
            selected_school_years = request.form.getlist('school_year')
            selected_school_years = convert_float_list_to_int(selected_school_years)
            
            selected_school_types = request.form.getlist('school_type')
            
            selected_course_names = request.form.getlist('course_name')
            
            selected_availabilities = request.form.getlist('availability')
            selected_availabilities = [avail.lower() == 'true' for avail in selected_availabilities]
            
            lessons_per_relation = request.form.get('lessons_per_relation')
            
            selected_tutor_types = request.form.getlist('tutor_types')
            selected_tutor_types = convert_float_list_to_int(selected_tutor_types)
            
            no_lesson_tutor = request.form.get('no_lesson_tutor')
            
            start_date = request.form.get('start_date')
            
            end_date = request.form.get('end_date')

                    use_location_filter = request.form.get('use_location_filter')
        latitude_input = request.form.get('latitude_input')
        longitude_input = request.form.get('longitude_input')
        distance_km = request.form.get('distance_km')

        try:
            latitude_input = float(latitude_input) if latitude_input else None
            longitude_input = float(longitude_input) if longitude_input else None
            distance_km = float(distance_km) if distance_km else None
        except ValueError:
            latitude_input = longitude_input = distance_km = None

            
            selected_excluded = request.form.getlist('excluded')
            selected_excluded = [exclude.lower() == 'true' for exclude in selected_excluded]
            
            if lessons_per_relation:
              try:
                lessons_per_relation = float(lessons_per_relation)
              except ValueError:
                lessons_per_relation = None 
            else:
                lessons_per_relation = 0
            
            if start_date:
              try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
              except ValueError:
                start_date = None 
            else:
                start_date = None
                
            if end_date:
              try:
                end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
              except ValueError:
                end_date = None 
            else:
                end_date = None
            
      # Apply additional filters based on user selections
            if selected_school_levels:
                if '-Empty-' in selected_school_levels:
                    filtered_df = filtered_df[filtered_df['school_level'].isnull() | filtered_df['school_level'].isin(selected_school_levels)]
                else:
                    filtered_df = filtered_df[filtered_df['school_level'].isin(selected_school_levels)]

            if selected_school_years:
                if '-Empty-' in selected_school_years:
                    filtered_df = filtered_df[filtered_df['school_year'].isnull() | filtered_df['school_year'].isin(selected_school_years)]
                else:
                    filtered_df = filtered_df[filtered_df['school_year'].isin(selected_school_years)]

            if selected_school_types:
                if '-Empty-' in selected_school_types:
                    filtered_df = filtered_df[filtered_df['school_type'].isnull() | filtered_df['school_type'].isin(selected_school_types)]
                else:
                    filtered_df = filtered_df[filtered_df['school_type'].isin(selected_school_types)]

            if selected_course_names:
                if '-Empty-' in selected_course_names:
                    filtered_df = filtered_df[filtered_df['course_name'].isnull() | filtered_df['course_name'].isin(selected_course_names)]
                else:
                    filtered_df = filtered_df[filtered_df['course_name'].isin(selected_course_names)]
                    
            if selected_availabilities:
                if '-Empty-' in selected_availabilities:
                    filtered_df = filtered_df[filtered_df['availability'].isnull() | filtered_df['availability'].isin(selected_availabilities)]
                else:
                    filtered_df = filtered_df[filtered_df['availability'].isin(selected_availabilities)]
              
            if selected_tutor_types:
                if '-Empty-' in selected_tutor_types:
                    filtered_df = filtered_df[filtered_df['tutor_category'].isnull() | filtered_df['tutor_category'].isin(selected_tutor_types)]
                else:
                    filtered_df = filtered_df[filtered_df['tutor_category'].isin(selected_tutor_types)]
                    
            if no_lesson_tutor:
                temp_df = filtered_df.fillna({'lessons_per_relation': 0})
                if lessons_per_relation is not None:
                  filtered_df = temp_df[temp_df['lessons_per_relation'] >= lessons_per_relation]
            else:
                if lessons_per_relation is not None:
                  temp_df = filtered_df[pd.notna(filtered_df['lessons_per_relation'])]
                  filtered_df = temp_df[temp_df['lessons_per_relation'] >= lessons_per_relation]
                  
            if selected_excluded:
                if '-Empty-' in selected_excluded:
                    filtered_df = filtered_df[filtered_df['excluded_from_search'].isnull() | filtered_df['excluded_from_search'].isin(selected_excluded)]
                else:
                    filtered_df = filtered_df[filtered_df['excluded_from_search'].isin(selected_excluded)]
                    
            if start_date:
                filtered_df = filtered_df[filtered_df['recent_lesson'] >= start_date]

            if end_date:
                filtered_df = filtered_df[filtered_df['recent_lesson'] <= end_date]

            if (
            use_location_filter == "Yes"
            and latitude_input is not None
            and longitude_input is not None
            and distance_km is not None
        ):
            filtered_df["distance_to_point"] = filtered_df.apply(
                lambda row: haversine(latitude_input, longitude_input, row["latitude"], row["longitude"]),
                axis=1
            )
            filtered_df = filtered_df[filtered_df["distance_to_point"] <= distance_km]
        
      # Filter tutors based on the final filters
            tutor_numbers = filtered_df['tutor']
            Tutor_filtered = Tutor[Tutor['tutor'].isin(tutor_numbers)]
            category = filtered_df[['tutor', 'tutor_category', 'availability']].drop_duplicates()
            Tutor_filtered = pd.merge(Tutor_filtered, category, how = 'left', on = 'tutor')

      # Create the map with filtered tutors
            if not Tutor_filtered.empty:
                map_center = [Tutor_filtered['latitude'].mean(), Tutor_filtered['longitude'].mean()]
                tutors_map = folium.Map(location=map_center, zoom_start=7)

                for index, row in Tutor_filtered.iterrows():
                    unique_id = f"{row['tutor']}"
                    
                    circle = folium.Circle(
                        location=(row['latitude'], row['longitude']),
                        radius=row['max_travel_distance'] * 1000,
                        popup=f"""<div class='circle-popup'>
                          Tutor: {row['tutor']}<br><br>
                          Availability: {row['availability']}<br><br>
                          Tutor type: {row['tutor_category']}<br><br>
                          Excluded: {row['excluded_from_search']}<br><br>
                          Total lessons: {row['total_lessons']}<br><br>
                          Per relation: {row['lessons_per_relation']} lesson(s)<br><br>
                          Link: <a href="{ 'https://bijlesaanhuis.nl/profiel/' if row['country'] == 'nl' else 'https://lernigo.de/profil/' }{row['tutor']}" target="_blank">Profile</a>
                          </div>""",                        
                        #Color
                        #color=row['quantile_labels'],
                        fill = True,
                        fill_opacity = 0,
                    ).add_to(tutors_map)
                    
                    marker = folium.Marker(
                      location=(row['latitude'], row['longitude']),
                        popup=f"""<div class='marker-popup'>
                          Tutor: {row['tutor']}<br><br>
                          Availability: {row['availability']}<br><br>
                          Tutor type: {row['tutor_category']}<br><br>
                          Excluded: {row['excluded_from_search']}<br><br>
                          Total lessons: {row['total_lessons']}<br><br>
                          Per relation: {row['lessons_per_relation']} lesson(s)<br><br>
                          Link: <a href="{ 'https://bijlesaanhuis.nl/profiel/' if row['country'] == 'nl' else 'https://lernigo.de/profil/' }{row['tutor']}" target="_blank">Profile</a>
                          </div>""",                      
                        icon=folium.Icon(color='red', icon='info-sign'),
                    ).add_to(tutors_map)
                    
                    marker.options["customId"] = unique_id
                    circle.options["customId"] = unique_id

                map_html = tutors_map.get_root().render()
            else:
                map_html = "<p>No tutors available for the selected filters.</p>"
                
            Tutor_filtered = Tutor_filtered[['tutor','created_at', 'state', 'country', 'city', 'tutor_category', 'max_travel_distance', 'number_of_relations', 'lessons_per_relation', 'recent_lesson', 'excluded_from_search']]
            Tutor_filtered['created_at'] = Tutor_filtered['created_at'].str[:10]
            df_html = Tutor_filtered.to_html(classes='data', index=False, escape=False)

    return render_template('template.html', 
                           countries=countries, 
                           selected_country=selected_country,
                           availability=availability,
                           school_levels=school_levels, 
                           school_years=school_years, 
                           school_types=school_types, 
                           course_names=course_names,
                           excluded = excluded,
                           selected_school_levels=selected_school_levels,
                           selected_school_years=selected_school_years,
                           selected_school_types=selected_school_types,
                           selected_course_names=selected_course_names,
                           selected_availabilities=selected_availabilities,
                           selected_excluded = selected_excluded,
                           lessons_per_relation = lessons_per_relation,
                           no_lesson_tutor = no_lesson_tutor,
                           tutor_types = tutor_types,
                           selected_tutor_types = selected_tutor_types,
                           start_date = start_date,
                           end_date = end_date,
                           map_html=map_html,
                           df_html=df_html),
                           use_location_filter=use_location_filter,
    latitude_input=latitude_input,
    longitude_input=longitude_input,
    distance_km=distance_km


if __name__ == '__main__':
    app.run(debug=True)
