import streamlit as st
import pandas as pd
import requests
import datetime as dt
from datetime import datetime
import time
import json
import warnings
warnings.filterwarnings("ignore")



# Declare my functions ------------------------------



@st.cache_data(ttl='1h')
def get_access_token(first_token, email):
    url = "https://app.circle.so/api/v1/headless/auth_token" 
    headers = {"Authorization": "Bearer " + first_token}
    data = {"email": email}
    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 200:
        return 1 #a BAD EMAIL OR TOKEN
    return str("Bearer " + pd.json_normalize(response.json())['access_token'].iloc[0])


# get space IDs (maybe later have an option to display these??)
@st.cache_data(ttl='1h')
def get_space_ids(access_token):
    url = "https://app.circle.so/api/headless/v1/spaces"
    headers = {'Authorization': access_token}
    response = requests.get(url, headers=headers)
    data = response.json()
    df = pd.json_normalize(data)
    return df[['id', 'name', 'space_type']]

@st.cache_data(ttl='1h')
def pull_all_posts(access_token):
    space_id_df = get_space_ids(access_token)

    master_list = pd.DataFrame(columns=['post_type', 'space_type', 'display_title', 'comment_count', 'user_likes_count', 'created_at', 'author.name', 'space.name'])
    # Loop through each space ID in the provided DataFrame
    for space_id in space_id_df['id']:
        base_url = f"https://app.circle.so/api/headless/v1/spaces/{space_id}/posts?sort=latest&per_page=100&page="
        headers = {'Authorization': access_token}
        df_all = pd.DataFrame()
        page = 1  # Start with page 1

        while True:
            url = base_url + str(page)
            response = requests.get(url, headers=headers)
            data = response.json()  # Parse the JSON response
            
            # Check if there are any records in the response
            if not data.get('records'):
                break

            # Extract the records field
            records = data['records']

            # Flatten the JSON data and select desired fields
            df = pd.json_normalize(records)

            # Select the relevant columns
            df = df[[
                'post_type', 'display_title', 'comment_count', 'user_likes_count', 
                'created_at', 'author.name', 'space.name'
            ]]

            # Concatenate to the main DataFrame
            df_all = pd.concat([df_all, df], ignore_index=True)

            # Check for the next page
            if not data.get("has_next_page", False):
                break

            page += 1
            time.sleep(.25)  # To avoid hitting rate limits

        # Append the posts from this space to the master list
        master_list = pd.concat([master_list, df_all], ignore_index=True)

    # Convert 'created_at' to datetime format
    master_list['created_at'] = pd.to_datetime(master_list['created_at'], errors='coerce')

    # FILTER OUT ANY POSTS THAT ARE EVENTS HERE...
    master_list = master_list[master_list['post_type'] != "event"]


    # Optionally sort by 'user_likes_count' or other criteria
    master_list_sorted = master_list.sort_values(by='user_likes_count', ascending=False)
    return master_list_sorted

@st.cache_data(ttl='1h')
def pull_all_events(access_token):
    url = "https://app.circle.so/api/headless/v1/community_events?per_page=100&past_events=True"
    headers = {'Authorization': access_token}
    response = requests.get(url, headers=headers)
    data = response.json()
    records = data['records']
    event_df = pd.json_normalize(records)
    event_df = event_df[~event_df['space.name'].str.contains('Moderator Training Space', na=False)]
    filt = event_df[['name','event_attendees.count', 'created_at', 'comment_count', 'user_likes_count',  
      'author.name', 'event_setting_attributes.duration_in_seconds', 'space.name' ]]

    filt = filt.rename(columns={
        'name': 'Event_Title',
        'event_attendees.count': 'Attendees',
        'created_at': 'Date',
        'comment_count': 'Comments',
        'user_likes_count': 'Likes',
        'author.name': 'Author_Name',
        'event_setting_attributes.duration_in_seconds': 'Length_Minutes',
        'space.name': 'Space_Name'
    })

    # Format the 'Date' column to show only 'YYYY-MM-DD'
    filt['Date'] = pd.to_datetime(filt['Date']).dt.strftime('%Y-%m-%d')

    # Convert 'Length.Minutes' from seconds to minutes (if needed)
    filt['Length_Minutes'] = filt['Length_Minutes'] / 60

    # Optional: Round the 'Length.Minutes' to a specific decimal place
    filt['Length_Minutes'] = filt['Length_Minutes'].round(1)
    return filt
        

def pull_most_valuable_people(df, top_number, weights, month=True, specific_month=None, specific_year=None, filter_admins=False):
    

    if filter_admins:
        # raw_df = pd.DataFrame(df)
        # df_no_gigg = raw_df[~raw_df['email'].str.contains('gigg', case=False, na=False)]
        df = df[~df['author.name'].str.contains('admin', case=False, na=False)]

    # MONTH STUFF
    if month == 1:
        current_year = datetime.now().year
        current_month = datetime.now().month
        df = df.loc[(df['created_at'].dt.year == current_year) & (df['created_at'].dt.month == current_month)]
    # elif month == 2:
    #     df = df.loc[(df['created_at'].dt.year == specific_year) & (df['created_at'].dt.month == specific_month)]

    df['post_type_weight'] = df['post_type'].map(weights)
    df['worth'] = (df['user_likes_count'] * weights['like']) + \
              (df['comment_count'] * weights['comment']) + \
              (df['post_type_weight'] * 10)

    user_worth_df = df.groupby('author.name', as_index=False).agg({'worth': 'sum'})
    user_worth_df.sort_values(by='worth', ascending=False, inplace=True)

    shortened = user_worth_df.head(top_number)
    total_worth = shortened['worth'].sum()
    user_worth_df.loc[:, 'worth_percentage'] = (user_worth_df['worth'] / total_worth * 100)
    user_worth_df = user_worth_df.sort_values(by='worth', ascending=False)

    user_worth_df = user_worth_df.rename(columns={
    # 'display_title': 'Title',
    'author.name': 'Author',
    'worth': 'Worth',
    'worth_percentage': 'Worth_Percentage',
    # 'comment_count': 'Comments',
    # 'user_likes_count': 'Likes',
    # 'created_at': 'Date'
    })
    user_worth_df = user_worth_df.reset_index(drop=True)
    return user_worth_df.head(top_number)


def pull_most_valuable_posts(df, top_number, weights, month=0, specific_month=None, specific_year=None, space_name="All", filter_admins=False):
    # maybe add that you can filter by a specific SPACE ---> would need to SHOW the space names somewhere...
    #like have a dropdown of all the space names...? might lead to more problems idk
    # if month == 0: # do nothing

    if filter_admins:
        # raw_df = pd.DataFrame(df)
        # df_no_gigg = raw_df[~raw_df['email'].str.contains('gigg', case=False, na=False)]
        df = df[~df['author.name'].str.contains('admin', case=False, na=False)]

    if month == 1:
        current_year = datetime.now().year
        current_month = datetime.now().month
        df = df.loc[(df['created_at'].dt.year == current_year) & (df['created_at'].dt.month == current_month)]
    # elif month == 2:
    #     df = df.loc[(df['created_at'].dt.year == specific_year) & (df['created_at'].dt.month == specific_month)]
    
    df['post_type_weight'] = df['post_type'].map(weights)
    df['worth'] = (df['user_likes_count'] * weights['like']) + \
              (df['comment_count'] * weights['comment']) + \
              (df['post_type_weight'] * 10)

    df.sort_values(by='worth', ascending=False, inplace=True)
    shortened = df.head(top_number)
    total_worth = shortened['worth'].sum()
    shortened.loc[:, 'worth_percentage'] = (shortened['worth'] / total_worth * 100)


    shortened = shortened.rename(columns={
    'display_title': 'Title',
    'author.name': 'Author',
    'worth': 'Worth',
    'worth_percentage': 'Worth_Percentage',
    'comment_count': 'Comments',
    'user_likes_count': 'Likes',
    'created_at': 'Date'
    })
    shortened = shortened.reset_index(drop=True)
    shortened['Date'] = pd.to_datetime(shortened['Date']).dt.strftime('%Y-%m-%d')
    return shortened[['Title', 'Author', 'Worth', 'Worth_Percentage', 'Comments', 'Likes', 'Date']]
#shortened[['display_title', 'author.name', 'worth', 'worth_percentage', 'comment_count', 'user_likes_count', 'created_at']]



    # //month == 0 --> don't filter anything
    # month == 1 --> filter to this current month so far
    # month == 2 XX other specific month, get the others working first
    # month == 3 XX other range,,,,,,,









# Actual Page Stuff ----------------------------------

st.set_page_config(
    page_title='Post Valuation',
    page_icon=':sparkles:'
)


'''
# Post and Person Valuation:
This is an app for finding the most valuable posts and people in each community. It may take a couple minutes to pull all the posts from the API at the start.

### To Get Your Token:
To use this app, you need a Circle Headless Token. If you are an admin for a community, you can click on the community name/drop down in the top left corner of the community site. 
If you navigate to the developer's page and then the token page, you can create a Headless token (not V1 or V2 or Data!!). 
You only need to create a Headless token once for each community because you can always use the same token after that.
'''






# Get the access key and choose People/Posts or Events --------------------------------

first_token = st.text_input("First token here:", "")
email = st.text_input("Email here:", "")
if first_token != "" and email != "":
    atoken = get_access_token(first_token, email)
    if atoken == 1:
        st.error('Bad token or email, please try again')
    else:
        st.write(":white_check_mark: Good token and email, now we are ready to pull data from the APIs.")
        st.write("Because Circle does not allow us to see the hosts/cohosts of livestream events at this time, we cannot assign worth to a person for livestream events the same as we can image or text posts. Consequently, they must be viewed seperately right now.")
        
        # pull_button = st.button("Pull all Posts")
        # members = pull_all_posts(atoken)
        
#         with st.form("first_form"):
#             data_option_map = {
#                 0: "Basic/Image Post Data",
#                 1: "Events Data"
#             }
#             data_selection = st.segmented_control(
#                 "Choose what to pull: ",
#                 options=data_option_map.keys(),
#                 format_func=lambda option: data_option_map[option],
#                 selection_mode="single",
#                 default=0 #think this is how it works
#             )
#             first_form_submit = st.form_submit_button("Submit")
#         if first_form_submit:

# # If People/Posts was chosen -----------------------------------------------------

#             if data_selection == 0: #PP
#                 members = pull_all_posts(atoken)
#                 with st.form("pp_form"):
#                     st.write("Choose the filters you want here: ")
#                     type_option_map = {
#                         0: "People",
#                         1: "Posts",
#                     }
#                     post_or_people_selection = st.segmented_control(
#                         "Do you want to look at the most valuable people or individual posts?",
#                         options=type_option_map.keys(),
#                         format_func=lambda option: type_option_map[option],
#                         selection_mode="single",
#                         default=0 #think this is how it works
#                     )

#                     picks = st.slider("How many do you want to pick?", 1, 20, 5)

#                     st.write("Choose the worth weights:")
#                     like_weight = st.slider("Like Weight", 0, 10, 1)
#                     comment_weight = st.slider("Comment Weight", 0, 10, 2)
#                     basic_weight = st.slider("Text Post Weight", 0, 10, 1)
#                     image_weight = st.slider("Image Post Weight", 0, 10, 2)

#                     weights = {
#                         'like': like_weight,
#                         'comment': comment_weight,
#                         'basic': basic_weight,
#                         'image': image_weight
#                     }

#                     #Radio button to do a current month, a specific month/year, or a range...
#                     st.write("What time range do you want to pull posts from")
#                     time_option_map = {
#                         0: "All Time",
#                         1: "This Month",
#                         2: "Other Specific Month",
#                         # 3: "Other Time Range"
#                     }
#                     time_selection = st.segmented_control(
#                         "Choose what to pull: ",
#                         options=time_option_map.keys(),
#                         format_func=lambda option: time_option_map[option],
#                         selection_mode="single",
#                         default=0 #think this is how it works
#                     )
#                     # month_pick = st.selectbox(
#                     #     "Choose the month to look at posts from",
#                     #     ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
#                     # )
#                     # year_pick = st.number_input("Year", 2024, 2025)
#                     p_submit = st.form_submit_button('Submit my picks')
#                     if p_submit:
#                         try:
#                             if post_or_people_selection == 0: #PEOPLE
#                                 st.dataframe(pull_most_valuable_people(members, top_number=picks, weights = weights, month=time_selection))
#                             elif post_or_people_selection == 1: #POSTS
#                                st.dataframe(pull_most_valuable_posts(members, top_number=picks, weights = weights, month=time_selection))
#                         except ValueError as e:
#                             st.error(f"There are not {picks} members that fit these parameters. Please try a smaller number or choose different filters. ")

# # If Events was chosen -----------------------------------------------------
#             elif data_selection == 1: #events
#                     event_data = pull_all_events(atoken)
#                     st.dataframe(event_data) 



# If the token was bad.......
else:
    atoken = 0
    members = st.empty()
    event_data = st.empty()






event_button = st.button("Pull and Display Event Data:")
if event_button:
    if atoken == 0 or atoken == 1:
        st.toast("Can't pull events with a bad token")
    else:
        event_data = pull_all_events(atoken)
        st.dataframe(event_data)



with st.form("pp_form"):
    st.write("Filter post or people data: ")
    type_option_map = {
        0: "People",
        1: "Posts",
    }
    post_or_people_selection = st.segmented_control(
        "Do you want to look at the most valuable people or individual posts?",
        options=type_option_map.keys(),
        format_func=lambda option: type_option_map[option],
        selection_mode="single",
        default=0 #think this is how it works
    )

    picks = st.slider("How many do you want to pick?", 1, 20, 5)

    st.write("Choose the worth weights:")
    like_weight = st.slider("Like Weight", 0, 10, 1)
    comment_weight = st.slider("Comment Weight", 0, 10, 2)
    basic_weight = st.slider("Text Post Weight", 0, 10, 1)
    image_weight = st.slider("Image Post Weight", 0, 10, 2)

    weights = {
        'like': like_weight,
        'comment': comment_weight,
        'basic': basic_weight,
        'image': image_weight
    }

    #Radio button to do a current month, a specific month/year, or a range...
    st.write("What time range do you want to pull posts from")
    time_option_map = {
        0: "All Time",
        1: "This Month",
        2: "Other Specific Month",
        # 3: "Other Time Range"
    }
    time_selection = st.segmented_control(
        "Choose what to pull: ",
        options=time_option_map.keys(),
        format_func=lambda option: time_option_map[option],
        selection_mode="single",
        default=0 #think this is how it works
        )
                    # month_pick = st.selectbox(
                    #     "Choose the month to look at posts from",
                    #     ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
                    # )
                    # year_pick = st.number_input("Year", 2024, 2025)
    
    
    filter_admins_check = st.checkbox("Filter out names containing: Admin", value = True)
    
    
    
    
    
    p_submit = st.form_submit_button('Submit my picks')
    if p_submit:

        #assuming that members has been populated by then?
        if atoken == 0 or atoken == 1:
            st.toast("Can't pull the posts with a bad token")
        else:
            members = pull_all_posts(atoken)
            try:
                if post_or_people_selection == 0: #PEOPLE
                    st.dataframe(pull_most_valuable_people(members, top_number=picks, weights = weights, month=time_selection, filter_admins=filter_admins_check))
                elif post_or_people_selection == 1: #POSTS
                    st.dataframe(pull_most_valuable_posts(members, top_number=picks, weights = weights, month=time_selection, filter_admins=filter_admins_check))
            except ValueError as e:
                st.error(f"There are not {picks} members that fit these parameters. Please try a smaller number or choose different filters. ")

