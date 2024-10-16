from flask import Flask, render_template, request
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

# Load the datasets
Courses = pd.read_csv('Courses.csv')
Tutor = pd.read_csv('Tutor.csv')

@app.route('/', methods=['GET', 'POST'])
def index():
    # Initialize variables
    filtered_df = Courses.copy()
    temp_df = pd.DataFrame()
    countries = Courses['country'].unique().tolist()
    school_levels = school_years = school_types = course_names = availability = []
    map_html = None
    selected_country = None
    selected_school_levels = selected_school_years = selected_school_types = selected_course_names = selected_availabilities = lessons_per_relation = no_lesson_tutor = []
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

            # Handle the second form submission for additional filters
            selected_school_levels = request.form.getlist('school_level')  
            
            selected_school_years = request.form.getlist('school_year')
            selected_school_years = convert_float_list_to_int(selected_school_years)
            
            selected_school_types = request.form.getlist('school_type')
            
            selected_course_names = request.form.getlist('course_name')
            
            selected_availabilities = request.form.getlist('availability')
            selected_availabilities = [avail.lower() == 'true' for avail in selected_availabilities]
            
            lessons_per_relation = request.form.get('lessons_per_relation')
            
            if lessons_per_relation:
              try:
                lessons_per_relation = float(lessons_per_relation)
              except ValueError:
                lessons_per_relation = None 
            else:
                lessons_per_relation = 0
            
            no_lesson_tutor = request.form.get('no_lesson_tutor')
            
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
            
            temp_df = Tutor[['tutor', 'lessons_per_relation']]
            filtered_df = pd.merge(filtered_df, temp_df, how = 'left', on = 'tutor')
                    
            if no_lesson_tutor:
                temp_df = filtered_df['lessons_per_relation'].fillna(0)
                if lessons_per_relation is not None:
                  filtered_df = temp_df[temp_df['lessons_per_relation'] >= lessons_per_relation]
            else:
                if lessons_per_relation is not None:
                  temp_df = filtered_df[pd.notna(filtered_df['lessons_per_relation'])]
                  filtered_df = temp_df[temp_df['lessons_per_relation'] >= lessons_per_relation]
            
            # Filter tutors based on the final filtered courses
            tutor_numbers = filtered_df['tutor']
            Tutor_filtered = Tutor[Tutor['tutor'].isin(tutor_numbers)]

            # Step 3: Create the map with filtered tutors
            if not Tutor_filtered.empty:
                map_center = [Tutor_filtered['latitude'].mean(), Tutor_filtered['longitude'].mean()]
                tutors_map = folium.Map(location=map_center, zoom_start=7)

                for index, row in Tutor_filtered.iterrows():
                    folium.Circle(
                        location=(row['latitude'], row['longitude']),
                        radius=row['max_travel_distance'] * 1000,
                        popup=f"Tutor: {row['tutor']}<br>Lessons per relation: {row['lessons_per_relation']}",
                        color="blue",
                    ).add_to(tutors_map)
                    
                    folium.Marker(
                      location=(row['latitude'], row['longitude']),
                      popup=f"Tutor: {row['tutor']}<br>Lessons per relation: {row['lessons_per_relation']}",
                      icon=folium.Icon(color='red', icon='info-sign'),  
                    ).add_to(tutors_map)

                map_html = tutors_map._repr_html_()
            else:
                map_html = "<p>No tutors available for the selected filters.</p>"
                
            df_html = Tutor_filtered.to_html(classes='data', index=False, escape=False)

    return render_template('template.html', 
                           countries=countries, 
                           selected_country=selected_country,
                           availability=availability,
                           school_levels=school_levels, 
                           school_years=school_years, 
                           school_types=school_types, 
                           course_names=course_names, 
                           selected_school_levels=selected_school_levels,
                           selected_school_years=selected_school_years,
                           selected_school_types=selected_school_types,
                           selected_course_names=selected_course_names,
                           selected_availabilities=selected_availabilities,
                           lessons_per_relation = lessons_per_relation,
                           no_lesson_tutor = no_lesson_tutor,
                           map_html=map_html,
                           df_html=df_html)

if __name__ == '__main__':
    app.run(debug=True)
