from flask import Flask, request, send_file, render_template
from tempfile import NamedTemporaryFile
from bs4 import BeautifulSoup
import requests
from datetime import datetime, timedelta
import json
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops
from typing import List, Dict, Union
from io import BytesIO
from typing import Tuple
import re
import os
import logging

current_year = datetime.now().year
month = datetime.now().strftime('%m')
day = datetime.now().strftime('%d')
current_date = datetime.now()
formatted_date = current_date.strftime("%B %d").lstrip("0")
google_json_app_api_key = 'AIzaSyAsBNzBt73LQlaT4ewZPCIEumtDoh0H73w'

def convert_star_rating(star_rating):
    full_stars = star_rating.count('★')
    half_star = 0.5 if '½' in star_rating else 0
    return str(full_stars + half_star)

def extract_movie_details(row):
    name = row.find('td', class_='td-film-details').find('h3').find('a').text.strip()
    like = row.find('td', class_='td-like').find('span', class_='icon-liked') is not None
    rating_element = row.find('td', class_='td-rating').find('span', class_='rating')
    rating = rating_element.text.strip() if rating_element else '0.0'
    rating = rating if rating else '0.0'
    released = row.find('td', class_='td-released').find('span').text.strip()
    return {
        "name": name,
        "like": like,
        "rating": rating,
        "released": released
    }

def split_title(title, max_length=30):
    """
    Split the title based on the specified max_length.
    """
    if len(title) <= max_length:
        return [title]

    # Split title into words
    words = title.split()

    # Find the break point
    line = ""
    for word in words:
        if len(line + word) <= max_length:
            line += word + " "
        else:
            break

    # Split the title into two parts
    first_part = line.strip()
    second_part = title[len(first_part):].strip()

    return [first_part, second_part]

def make_filename_safe(title: str) -> str:
    # Remove or replace any characters that are not allowed in filenames
    safe_title = re.sub(r"[^a-zA-Z0-9]", "_", title)
    
    # Replace spaces with underscores
    safe_title = safe_title.replace(" ", "_")
    
    # Ensure the resulting string doesn't exceed a certain length (e.g., 250 characters)
    MAX_LENGTH = 250
    if len(safe_title) > MAX_LENGTH:
        safe_title = safe_title[:MAX_LENGTH]
    
    return safe_title

def determine_movie_thumbnail_query(movie_details: dict) -> Tuple[str, str]:
    if not movie_details:
        return None, None, None

    liked_movies_with_year = [(year, movie) for year, movies in movie_details.items() for movie in movies if isinstance(movie, dict) and movie.get('like')]

    total_movies = sum(len(movies) for movies in movie_details.values())

    if total_movies == 1:
        # Handle the case where there is a single movie.
        single_movie = next(movie for movies in movie_details.values() for movie in movies if isinstance(movie, dict))
        year = next(year for year in movie_details.keys())
        return f"{single_movie['name']} ({single_movie['released']})", year, single_movie['name']

    elif len(liked_movies_with_year) == 1:
        # Handle the case where there is a single liked movie.
        return f"{liked_movies_with_year[0][1]['name']} ({liked_movies_with_year[0][1]['released']})", liked_movies_with_year[0][0], liked_movies_with_year[0][1]['name']

    else:
        if liked_movies_with_year:
            earliest_liked_movie = min(liked_movies_with_year, key=lambda x: x[0])[1]
            year = min(liked_movies_with_year, key=lambda x: x[0])[0]
            return f"{earliest_liked_movie['name']} ({earliest_liked_movie['released']})", year, earliest_liked_movie['name']
        else:
            all_movies = [(year, movie) for year, movies in movie_details.items() for movie in movies if isinstance(movie, dict) and 'name' in movie]
            if all_movies:
                earliest_movie = min(all_movies, key=lambda x: x[0])[1]
                year = min(all_movies, key=lambda x: x[0])[0]
                return f"{earliest_movie['name']} ({earliest_movie['released']})", year, earliest_movie['name']
            else:
                return None, None, None  # If there are no movies at all.
        
def download_thumbnail(api_key, query):
    params = {
        'cx': '117249e9d52ed43b5', 
        'excludeTerms': 'poster',
        'imgType': 'photo',
        'safe': 'off',
        'searchType': 'image',
        'fields': 'items.fileFormat, items.title, items.htmlTitle, items.link, items.image.height, items.image.width, items.image.byteSize',
        'key': api_key,
        'q': query
    }

    response = requests.get('https://customsearch.googleapis.com/customsearch/v1', params=params)
    
    if response.status_code == 200:
        results = response.json()['items']

        def is_image_suitable(item):
            """Check if the image meets the criteria, including the exclusion condition."""
            width = item['image']['width']
            height = item['image']['height']
            image_url = item['link']
            
            # Exclude images from mubi.com that have 'overlaid' in their filenames
            if 'mubicdn.net' in image_url and 'overlaid' in image_url:
                return False
            
            # Additional conditions can be placed here (e.g., aspect ratio, minimum size, etc.)
            return width > height

        # Check the first three images for a width of at least 1280 pixels
        for item in results[:3]:  # Limiting the loop to the first three items
            width = item['image']['width']
            if width >= 1280 and is_image_suitable(item):
                image_url = item['link']
                image_response = requests.get(image_url)

                if image_response.status_code == 200:
                    img = Image.open(BytesIO(image_response.content))
                    return img
                else:
                    print(f"Failed to download image: {image_url}")
                break  # If a suitable image is found among the first three, we use it

        # If none of the first three images fit, fall back to the original criteria
        width_conditions = [4092, 1920, 1280, 600, 480]
        suitable_image = None

        for width_limit in width_conditions:
            max_width = 0

            for item in results:
                width = item['image']['width']
                height = item['image']['height']

                # Check for suitability, including the exclusion of certain mubi.com images
                if is_image_suitable(item) and width <= width_limit and width <= 2.5 * height and width > max_width:
                    suitable_image = item
                    print(suitable_image)
                    max_width = width

            if suitable_image:
                break

        # If a suitable image is found based on original criteria, download it
        if suitable_image:
            image_url = suitable_image['link']
            image_response = requests.get(image_url)

            if image_response.status_code == 200:
                img = Image.open(BytesIO(image_response.content))
                return img
            else:
                print(f"Failed to download image: {image_url}")

        else:
            print("No suitable image found.")
            return None

    else:
        print(f"API request failed with status code {response.status_code}")
        return None

def add_padding(img, new_width, new_height):
    pad_width = (new_width - img.width) // 2
    pad_height = (new_height - img.height) // 2
    return ImageOps.expand(img, (pad_width, pad_height, pad_width, pad_height), fill='black')

def adjust_image_aspect_ratio(img: Image.Image, target_aspect=(4, 3)) -> Image.Image:
    img = img.convert('RGB')
    width, height = img.size
    aspect_ratio = width / height
    target_aspect_ratio = target_aspect[0] / target_aspect[1]
    
    tolerance = 0.05

    # If the image is already in the target aspect ratio
    if abs(aspect_ratio - target_aspect_ratio) < 1e-5:
        return img

    # Determine new dimensions based on target aspect ratio
    new_width = int(height * target_aspect_ratio)
    new_height = int(width / target_aspect_ratio)
    
    # Close to 4:3 or less, add vertical black bars
    if aspect_ratio <= (target_aspect_ratio + tolerance):
        return add_padding(img, new_width, height)
    
    # Greater than 1.6 or specific widescreen formats, add horizontal black bars
    elif aspect_ratio > 1.6 or abs(aspect_ratio - 2.39) < tolerance or abs(aspect_ratio - 16/9) < tolerance:
        return add_padding(img, width, new_height)
    
    else:
        left_margin = (width - new_width) // 2
        return img.crop((left_margin, 0, left_margin + new_width, height))
                
def add_caption(img: Image.Image, text: str, movie_still_date: str, caption_font, scale_factor=1.02, vertical_adjust=-0.1):
    """
    Adds a caption to the bottom of the image.
    """
    draw = ImageDraw.Draw(img)
    
    try:
        font = caption_font
    except IOError:
        font = ImageFont.load_default()

    # Get dimensions of both the text and the movie_still_date using textbbox
    text_bbox = draw.textbbox((0, 0), text + movie_still_date, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    # Calculate the position for the text and the rounded rectangle
    img_width, img_height = img.size
    rect_center_x = img_width // 2
    rect_center_y = (img_height - text_height - 30) - 30  # Moved 50 pixels higher

    outer_rounded_rectangle_radius=24
    outer_rounded_rectangle_height=38
    inner_rounded_rectangle_height = 18
    padding = ((outer_rounded_rectangle_height-inner_rounded_rectangle_height)/2)
    inner_rounded_rectangle_radius = outer_rounded_rectangle_radius - padding

    # Draw grey background rectangle
    upper_left_grey = (rect_center_x - int((text_width + outer_rounded_rectangle_height) * scale_factor) // 2, rect_center_y - int((text_height + outer_rounded_rectangle_height) * scale_factor) // 2)
    lower_right_grey = (rect_center_x + int((text_width + outer_rounded_rectangle_height) * scale_factor) // 2, rect_center_y + int((text_height + outer_rounded_rectangle_height) * scale_factor) // 2)
    draw.rounded_rectangle([upper_left_grey, lower_right_grey], radius=int(outer_rounded_rectangle_radius * scale_factor), fill=('darkgrey'))  # Orange background

    # Draw white rectangle (4px padding included)
    upper_left = (rect_center_x - int((text_width + inner_rounded_rectangle_height) * scale_factor) // 2, rect_center_y - int((text_height + inner_rounded_rectangle_height) * scale_factor) // 2)
    lower_right = (rect_center_x + int((text_width + inner_rounded_rectangle_height) * scale_factor) // 2, rect_center_y + int((text_height + inner_rounded_rectangle_height) * scale_factor) // 2)
    draw.rounded_rectangle([upper_left, lower_right], radius=int(inner_rounded_rectangle_radius * scale_factor), fill=('#15181D'))  # LetterboxdGrey background

    # Center the text within the rounded rectangle
    text_x = rect_center_x - text_width // 2
    text_y = rect_center_y - text_height // 2

    # Apply vertical adjustment
    text_y -= int(text_height * vertical_adjust)

    # Draw the text
    draw.text((text_x, text_y), text, font=font, fill='#FFFFFF')  # Black text

    # Calculate the width of the text using textbbox
    text_bbox = draw.textbbox((text_x, text_y), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    date_x = text_x + text_width

    # Draw the movie_still_date in dark grey next to the text
    draw.text((date_x, text_y), movie_still_date, font=font, fill='darkgrey')

    return img

app = Flask(__name__)

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    username = request.form['username']
    final_movie_details = {}
    for year in range(current_year-1, 2018, -1):  # Looping from current year to 2019
        url = f'https://letterboxd.com/{username}/films/diary/for/{year}/{month}/{day}'
        response = requests.get(url)
        html_content = response.text
        soup = BeautifulSoup(html_content, 'html.parser')
        movie_table = soup.find('table', id='diary-table')
        if movie_table is None:
            final_movie_details[year] = [{'movies': 'No cinema consumed.'}]  # Consistent format
            continue
        all_movie_details = []
        for row in movie_table.find('tbody').find_all('tr', class_='diary-entry-row'):
            movie_details = extract_movie_details(row)
            movie_details['rating'] = convert_star_rating(movie_details['rating'])
            all_movie_details.append(movie_details)
        final_movie_details[year] = all_movie_details
    final_json = json.dumps(final_movie_details, indent=2)

    # Create a blank image (or load a template)
    image = Image.open("source_files/template_snp-frame.png")
    width=1872
    height=1404
    font_path = "source_files/fonts/HelveticaNeueLTProBdCn.otf"
    font_path_subway = "source_files/fonts/HelveticaNeueLTProBd.otf"
    year_font_path = "source_files/fonts/HelveticaNeueLTProMd.otf"
    still_caption_font_path = "source_files/fonts/HelveticaNeueLTProBdCn.otf"
    font_size_year = 30
    font_size_subway = 76
    font_size_movie = int(font_size_year * 1.25)
    font_year = ImageFont.truetype(font_path, font_size_year)
    font_movie = ImageFont.truetype(font_path, font_size_movie)
    caption_font = ImageFont.truetype(font_path_subway, 48)
    font_date = ImageFont.truetype(font_path_subway, 200)
    heart_image = Image.open("noun-heart-17449_edit.png")

    # Redraw on the image with the adjusted positioning
    draw = ImageDraw.Draw(image)
    x_position = 225  # Starting x-position
    x_year_position = x_position - 50 # adjust year for indentation 
    y_position = int(0.40 * 1404)
    column_spacing = width // 2

    # Calculate the total number of movies
    total_movies = sum(len(movies) for movies in final_movie_details.values())
    # Determine the number of movies in the first column
    movies_in_first_column = total_movies // 2 + (total_movies % 2)  # If odd number, add 1 to the first column

    movie_count = 0
    current_column_movie_count = 0

    # Check if every year's "movies" consists only of the entry "No cinema consumed"
    only_no_cinema = all(len(year_data) == 1 and 'movies' in year_data[0] and year_data[0]['movies'] == "No cinema consumed" for year_data in final_movie_details.values())
    if not any(movies for movies in final_movie_details.values()):
        return render_template('no_movies_today.html')

    for year, movies in final_movie_details.items():
        is_no_cinema_year = len(movies) == 1 and 'movies' in movies[0] and movies[0]['movies'] == "No cinema consumed."
        
        # If it's a "No cinema consumed" year, skip the entire processing for this year
        if is_no_cinema_year:
            continue

        # Draw the year
        draw.text((x_year_position, y_position), str(year), font=font_year, fill='#00E054')
        y_position += 40  # Move down after drawing the year
        
        for movie in movies:
            if 'name' in movie:
                name_parts = split_title(movie['name'])
                released = movie['released']
                rating = movie['rating']
                
                # Calculate the total width of the title with its parts
                title_width = sum([draw.textbbox((0, 0), part, font=font_movie)[2] for part in name_parts])
                
                # Draw movie name, handling the possible split
                for idx, part in enumerate(name_parts):
                    draw.text((x_position, y_position), part, font=font_movie, fill='#FFFFFF')
                    # Only increase y_position if there's another part after this
                    if idx < len(name_parts) - 1:
                        y_position += 50
                        
                # Calculate position for movie released year using textbbox and draw it
                last_line_bbox = draw.textbbox((0, 0), name_parts[-1], font=font_movie)
                last_line_width = last_line_bbox[2] - last_line_bbox[0]
                released_bbox = draw.textbbox((0, 0), f"({released})", font=font_movie)
                released_text_width = released_bbox[2] - released_bbox[0]
                draw.text((x_position + last_line_width + 10, y_position), f"({released})", font=font_movie, fill='#FFFFFF')

                # Draw the rating only if it is more than 0 stars
                if rating != '0':
                    rating_bbox = draw.textbbox((0, 0), f"{rating} stars", font=font_movie)
                    rating_text_width = rating_bbox[2] - rating_bbox[0]
                    draw.text((x_position + last_line_width + released_text_width + 20, y_position), f"{rating} stars", font=font_movie, fill='#FFFFFF')

                # If the movie is liked, draw the heart image after the combined width of the last line of the title and the released year
                if movie["like"]:
                    total_last_line_width = last_line_width + released_text_width + 10  # 10 as buffer between title and released
                    heart_x_position = x_position + total_last_line_width + 10  # 10 as buffer between released and heart
                    heart_y_position = y_position
                    image.paste(heart_image, (int(heart_x_position), heart_y_position), heart_image)
            else:
                if only_no_cinema:
                    draw.text((x_position, y_position), movie.get("movies", "Unknown"), font=font_movie, fill='#FFFFFF')
            
            y_position += 50  # Move down after each movie
            movie_count += 1
            current_column_movie_count += 1
            
            # Check if we need to move to the second column
            if current_column_movie_count == movies_in_first_column:
                x_position += column_spacing
                x_year_position += column_spacing
                y_position = int(0.40 * 1404)
                current_column_movie_count = 0  # Reset the count for the second column
        
        y_position += 40  # Extra space between different years

    text_bbox = draw.textbbox((0, 0), formatted_date, font_date)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    img_width, img_height = image.size
    img_center_x = img_width // 2
    text_x = img_center_x - text_width // 2

    # Draw the text
    draw.text((text_x, 80), formatted_date, font=font_date, fill='#FFFFFF')

    # Save with timestamp
    time_str = current_date.strftime("%Y-%m-%d_%I%M%p")
    with NamedTemporaryFile(delete=False, suffix=f"{time_str}-frame.png") as temp_file:
        output_file = temp_file.name
        image.save(output_file)

    movie_still_query, year, movie_still_title = determine_movie_thumbnail_query(final_movie_details)

    if movie_still_query is not None:
        raw_still = download_thumbnail(google_json_app_api_key, movie_still_query)
        conformed_4_3_still = adjust_image_aspect_ratio(raw_still)

        movie_still_query = f"{movie_still_query}"
        movie_still_date = f" {year}"
        final_still_with_caption = add_caption(conformed_4_3_still, movie_still_query, movie_still_date, caption_font)
        filename_safe_movie_still_title = make_filename_safe(movie_still_title)
        with NamedTemporaryFile(delete=False, suffix=f"{time_str}-{filename_safe_movie_still_title}-frame.png") as temp_file_still:
            output_file_still = temp_file_still.name
            final_still_with_caption.save(output_file_still)

    return render_template('result.html', image1_url=output_file, image2_url=output_file_still)

if __name__ == '__main__':
    app.run()
