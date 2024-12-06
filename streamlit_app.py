import streamlit as st
import pandas as pd
import numpy as np
import requests
# import datetime as dt
from datetime import datetime
from dateutil.relativedelta import relativedelta
from datetime import datetime
import time
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
    master_list = pd.DataFrame(columns=['post_type', 'space_type', 'display_title', 'comment_count', 'user_likes_count', 'created_at', 'author.name', 'space.name', 'author.roles'])
    for space_id in space_id_df['id']:
        base_url = f"https://app.circle.so/api/headless/v1/spaces/{space_id}/posts?sort=latest&per_page=100&page="
        headers = {'Authorization': access_token}
        df_all = pd.DataFrame()
        page = 1  # Start with page 1
        while True:
            url = base_url + str(page)
            response = requests.get(url, headers=headers)
            data = response.json()
            if not data.get('records'):
                break
            records = data['records']
            df = pd.json_normalize(records)
            df = df[[
                'post_type', 'display_title', 'comment_count', 'user_likes_count', 
                'created_at', 'author.name', 'space.name', 'author.roles'
            ]]
            df_all = pd.concat([df_all, df], ignore_index=True)
            if not data.get("has_next_page", False):
                break
            page += 1
            time.sleep(.25)  # To avoid hitting rate limits
        master_list = pd.concat([master_list, df_all], ignore_index=True)
        
    master_list['created_at'] = pd.to_datetime(master_list['created_at'], errors='coerce')
    master_list = master_list[master_list['post_type'] != "event"]
    #RENAME columns here:
    master_list = master_list.rename(columns={
        'display_title': 'Title',
        'author.name': 'Author',
        'comment_count': 'Comments',
        'user_likes_count': 'Likes',
        'created_at': 'Date',
        'space.name': 'Space_Name',
        'post_type': 'Post_Type',
        'author.roles': 'Author_Roles'
    })
    master_list.sort_values(by='Date', ascending=False, inplace=True)
    return master_list[['Title', 'Author', 'Date', 'Likes', 'Comments', 'Post_Type', 'Space_Name', 'Author_Roles']]

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
      'author.name', 'event_setting_attributes.duration_in_seconds', 'space.name', 'author.roles']]

    filt = filt.rename(columns={
        'name': 'Event_Title',
        'event_attendees.count': 'Attendees',
        'created_at': 'Date',
        'comment_count': 'Comments',
        'user_likes_count': 'Likes',
        'author.name': 'Author',
        'event_setting_attributes.duration_in_seconds': 'Length_Minutes',
        'space.name': 'Space_Name',
        'author.roles':'Author_Roles'
    })

    # Format the 'Date' column to show only 'YYYY-MM-DD'
    filt['Date'] = pd.to_datetime(filt['Date']).dt.strftime('%Y-%m-%d')

    # Convert 'Length.Minutes' from seconds to minutes (if needed)
    filt['Length_Minutes'] = filt['Length_Minutes'] / 60

    # Optional: Round the 'Length.Minutes' to a specific decimal place
    filt['Length_Minutes'] = filt['Length_Minutes'].round(1)
    return filt[['Event_Title', 'Attendees', 'Author', 'Date', 'Likes', 'Comments', 'Length_Minutes', 'Space_Name', 'Author_Roles']]
        
def filter_events(df, weights, top_number=5):
    df['Worth'] = (df['Likes'] * weights['like']) + \
        (df['Comments'] * weights['comment']) + \
        (df['Attendees'] * weights['attendees']) + \
        (df['Length_Minutes'] * weights['duration'])
    df.sort_values(by="Worth", ascending=False, inplace=True)
    return df[['Event_Title', 'Worth', 'Date', 'Attendees', 'Author', 'Author_Roles']].head(top_number)


def pull_most_valuable_people(df, top_number, weights, month=True, specific_date='', 
                              filter_admins=False, filter_mods=False, amount=0):
    if filter_admins:
        df = df[~df['Author_Roles'].apply(lambda x: 'admin' in x)]
        df = df[~df['Author'].str.contains('admin', case=False, na=False)]
    
    if filter_mods:
        df = df[~df['Author_Roles'].apply(lambda x: 'moderator' in x)]


    # MONTH STUFF
    current_year = datetime.now().year
    current_month = datetime.now().month

    #if 0, then for ALL TIME
    if month == 1: # for current month
        df = df.loc[(df['Date'].dt.year == current_year) & (df['Date'].dt.month == current_month)]
    elif month == 2:# for LAST MONTH
        last_month_date = datetime.now() - relativedelta(months=1)
        last_month_year = last_month_date.year
        last_month = last_month_date.month
        df = df.loc[(df['Date'].dt.year == last_month_year) & (df['Date'].dt.month == last_month)]
    elif month == 3: #for a specific date
        specific_date = datetime.strptime(str(specific_date), '%Y-%m-%d')
        if specific_date > datetime.now() and specific_date.month != datetime.now().month:
            st.toast("Please choose a date in the PAST, not the future.")
        df = df.loc[(df['Date'].dt.year == specific_date.year) & (df['Date'].dt.month == specific_date.month)]
    # elif month == 4: for a different time range?





    df['post_type_weight'] = df['Post_Type'].map(weights)
    df.loc[:, 'Worth'] = (df['Likes'] * weights['like']) + \
                     (df['Comments'] * weights['comment']) + \
                     (df['post_type_weight'] * 10)

    user_worth_df = df.groupby('Author', as_index=False).agg({'Worth': 'sum'})
    # user_worth_df = df.groupby(['Author', ''], as_index=False).agg({'Worth': 'sum'})
    user_worth_df.sort_values(by='Worth', ascending=False, inplace=True)

    #check HERE if there is enough people to return the full number
    if len(user_worth_df) < top_number:
        st.toast("There were not enough people who posted in this time period to fulfill your request. Please choose a different period or fewer people.")

    shortened = user_worth_df.head(top_number)
    total_worth = shortened['Worth'].sum()
    user_worth_df.loc[:, 'Worth_Percentage'] = (user_worth_df['Worth'] / total_worth * 100)
    user_worth_df = user_worth_df.sort_values(by='Worth', ascending=False)
    user_worth_df = user_worth_df.reset_index(drop=True)

    if amount != 0:
        df = pd.DataFrame(user_worth_df)
        df['payment_amount'] = (df['Worth_Percentage'] / 100) * amount
        df['Rounded_Payment'] = np.floor(df['payment_amount'] * 100) / 100  # Round down
        difference = round(amount - df['Rounded_Payment'].sum(), 2)
        df['fraction'] = df['payment_amount'] - df['Rounded_Payment']
        df = df.sort_values(by='fraction', ascending=False)
        for i in range(int(difference * 100)):
            df.iloc[i, df.columns.get_loc('Rounded_Payment')] += 0.01
        df = df.drop(columns=['fraction', 'payment_amount'])
        df.sort_values(by='Rounded_Payment', ascending=False, inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df.head(top_number)
        
    return user_worth_df.head(top_number)

def pull_most_valuable_posts(df, top_number, weights, month=0, specific_date='',
                              filter_admins=False, filter_mods=False): #space_name="All",
    # maybe add that you can filter by a specific SPACE ---> would need to SHOW the space names somewhere...
    #like have a dropdown of all the space names...? might lead to more problems idk
    # if month == 0: # do nothing

    if filter_admins:
        df = df[~df['Author_Roles'].apply(lambda x: 'admin' in x)]
        df = df[~df['Author'].str.contains('admin', case=False, na=False)]
    
    if filter_mods:
        df = df[~df['Author_Roles'].apply(lambda x: 'moderator' in x)]

    # MONTH STUFF
    current_year = datetime.now().year
    current_month = datetime.now().month

    #if 0, then for ALL TIME
    if month == 1: # for current month
        df = df.loc[(df['Date'].dt.year == current_year) & (df['Date'].dt.month == current_month)]
    elif month == 2:# for LAST MONTH
        last_month_date = datetime.now() - relativedelta(months=1)
        last_month_year = last_month_date.year
        last_month = last_month_date.month
        df = df.loc[(df['Date'].dt.year == last_month_year) & (df['Date'].dt.month == last_month)]
    elif month == 3: #for a specific date
        specific_date = datetime.strptime(str(specific_date), '%Y-%m-%d')
        if specific_date > datetime.now() and specific_date.month != datetime.now().month:
            st.toast("Please choose a date in the PAST, not the future.")
        df = df.loc[(df['Date'].dt.year == specific_date.year) & (df['Date'].dt.month == specific_date.month)]


        #after filtering to the right dates, now check how many posts there are --- if not enough, send a TOAST up and return early
    #ACTUALLY THIS IS FOR THE POSTS, NOT THE PEOPLE PULLER
    if len(df) < top_number:
        st.toast(f"There are only {len(df)} posts from that time period. Please choose a different period or fewer posts.")
    
    df['post_type_weight'] = df['Post_Type'].map(weights)
    df['Worth'] = (df['Likes'] * weights['like']) + \
              (df['Comments'] * weights['comment']) + \
              (df['post_type_weight'] * 10)

    df.sort_values(by='Worth', ascending=False, inplace=True)
    shortened = df.head(top_number)
    total_worth = shortened['Worth'].sum()
    shortened.loc[:, 'Worth_Percentage'] = (shortened['Worth'] / total_worth * 100)
    shortened = shortened.reset_index(drop=True)
    shortened['Date'] = pd.to_datetime(shortened['Date']).dt.strftime('%Y-%m-%d')
    return shortened[['Title', 'Author', 'Worth', 'Worth_Percentage', 'Comments', 'Likes', 'Date']]

    # month == 0 --> don't filter anything
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
Make sure you remember what email/account you were using when you made the token because you will need that email below.
'''


st.link_button("See the Random Picker site for more instructions on generating tokens", "https://gigg-random-picker.streamlit.app/")


# Get the access key and choose People/Posts or Events --------------------------------



# mention that we need to get a new token every hour?????
first_token = st.text_input("Token here:", "")
email = st.text_input("Email here:", "")
if first_token != "" and email != "":
    atoken = get_access_token(first_token, email)
    if atoken == 1:
        st.error('Bad token or email, please try again')
    else:
        st.write(":white_check_mark: Good token and email, now we are ready to pull data from the APIs. Notice that the first time the posts are pulling may take a couple minutes.")
        st.write("Because Circle does not allow us to see the hosts/cohosts of livestream events at this time, we cannot assign worth to a person for livestream events the same as we can image or text posts. Consequently, they must be viewed seperately right now.")


# If the token was bad.......
else:
    atoken = 0
    members = st.empty()
    event_data = st.empty()



st.divider()
st.subheader("Quick Buttons:")
'''Get the top five values in different categories for the community with admins/moderators removed and default weights.
Like = 1
Comment = 2
Basic Post Type = 1
Image Post Type = 2
'''


top_five_this_month = st.button("5 most valuable posts this month so far")
if top_five_this_month:
    if atoken == 0 or atoken == 1:
            st.toast("Can't pull the posts with a bad token")
    else:
        members = pull_all_posts(atoken)
        try:
            weights = {
                'like': 1,
                'comment': 2,
                'basic': 1,
                'image': 2
            }
            st.dataframe(pull_most_valuable_posts(members, top_number=5, weights = weights, month=1, filter_admins=True, filter_mods=True))
        except ValueError as e:
            st.error(f"There are not 5 members that fit these parameters. Please try a smaller number or choose different filters. ")


top_five_all_time = st.button("5 most valuable community members of all time")
if top_five_all_time:
    if atoken == 0 or atoken == 1:
            st.toast("Can't pull the posts with a bad token")
    else:
        members = pull_all_posts(atoken)
        try:
            weights = {
                'like': 1,
                'comment': 2,
                'basic': 1,
                'image': 2
            }
            st.dataframe(pull_most_valuable_people(members, top_number=5, weights = weights, month=0, filter_admins=True, filter_mods=True))
        except ValueError as e:
            st.error(f"There are not 5 members that fit these parameters. Please try a smaller number or choose different filters. ")


top_five_events = st.button("5 most well attended events of all time")
if top_five_events:
    if atoken == 0 or atoken == 1:
            st.toast("Can't pull the posts with a bad token")
    else:
        events = pull_all_events(atoken)
        events.sort_values(by="Attendees", ascending=False, inplace=True)
        st.dataframe(events[['Event_Title', 'Attendees', 'Date', 'Author']].head(5))






# # make this a form?? with weights too????
# event_button = st.button("Pull and Display Event Data:")
# if event_button:
#     if atoken == 0 or atoken == 1:
#         st.toast("Can't pull events with a bad token")
#     else:
#         event_data = pull_all_events(atoken)
#         st.dataframe(event_data)


st.divider()
with st.form("e_form"):
    st.subheader("Filter events data: ")
    st.write("This section is for finding the most valuable events due to desired parameters.")
    picks_num = st.slider("How many do you want to pick?", 1, 10, 5)

    st.write("Choose the worth weights:")
    attendees_weight = st.slider("Attendees Weight", 0, 10, 3)
    like_weight = st.slider("Like Weight", 0, 10, 1)
    comment_weight = st.slider("Comment Weight", 0, 10, 2)
    duration_weight = st.slider("Duration (Minutes) Weight", 0, 10, 2)

    weights = {
        'like': like_weight,
        'comment': comment_weight,
        'attendees': attendees_weight,
        'duration': duration_weight
    }
    e_submit = st.form_submit_button('Submit my picks')
    if e_submit:

        #assuming that members has been populated by then?
        if atoken == 0 or atoken == 1:
            st.toast("Can't pull the posts with a bad token")
        else:
            events = pull_all_events(atoken)
            try:
                st.dataframe(filter_events(events, weights, picks_num))
            except ValueError as e:
                st.error(f"There may not be {picks_num} events that fit these parameters. Please try again with less events.")






st.divider()
with st.form("pp_form"):
    st.subheader("Filter post or people data: ")
    st.write("This section is for finding the most valuable posts or community contributers.")
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
        2: "Last Month",
        3: "Other Specific Month",
        # 4: "Other Time Range"
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
    
    st.write("If you want a specific month, choose any day in that month.")
    opt_date = st.date_input("Choose a month", value=None)

    
    filter_admins_check = st.checkbox("Filter out Admins", value = True)
    filter_mods_check = st.checkbox("Filter out Moderators", value = True)


    #optional - choose an amount to assign money to
    st.write("Optional When Filtering People:")
    payment_amount = st.number_input(
        label = "Input a dollar amount to see the distribution between top members", 
        min_value=0, max_value=10000, value="min"
    )
    
    
    p_submit = st.form_submit_button('Submit my picks')
    if p_submit:

        #assuming that members has been populated by then?
        if atoken == 0 or atoken == 1:
            st.toast("Can't pull the posts with a bad token")
        else:
            members = pull_all_posts(atoken)
            try:
                if post_or_people_selection == 0: #PEOPLE
                    st.dataframe(pull_most_valuable_people(members, top_number=picks, weights = weights, month=time_selection, specific_date=opt_date, filter_admins=filter_admins_check, filter_mods=filter_mods_check, amount = payment_amount))
                elif post_or_people_selection == 1: #POSTS
                    st.dataframe(pull_most_valuable_posts(members, top_number=picks, weights = weights, month=time_selection, specific_date=opt_date, filter_admins=filter_admins_check, filter_mods=filter_mods_check))
            except ValueError as e:
                st.error(f"There are not {picks} members that fit these parameters. Please try a smaller number or choose different filters. ")



st.divider()
"""Future features if circle ever gets back to us
- events where we know who hosted/cohosted
- filter by activity score
- OR SOMETHING THAT LETS YOU GET THE EMAIL/OTHER INFO ON A PERSON IF THEY PASTE IN THEIR NAME OR SOMETHING
"""






# #PAGE TWO

stats_button = st.button("Generate some statisitics about this data: ")
if stats_button:
    posts = pull_all_posts(atoken)
    post_counts = posts['author.name'].value_counts()
    highest_poster = post_counts.index[0]
    most_posts_count = post_counts.iloc[0]

    events = pull_all_events(atoken)
    st.write(f"The total number of posts made in this community is {len(posts)} posts.")
    st.write(f"The total number of livestream events is {len(events)} events.")
    st.write(f"The person with the most posts is {highest_poster} with {most_posts_count} posts.")
    st.write(f"The total number of community members with at least one post is {len(post_counts)}.")



next_month = datetime.now() + relativedelta(months=1)


with st.form("this form"):
    start_time = st.slider(
        "When do you start?",
        value=datetime(2024, 6, 1),
        min_value=datetime(2024,1,1),
        # max_value=datetime(2025,6,1),
        # max_value=next_month,
        format="MM/YY"
    )
    push = st.form_submit_button("HERE")
if push:
    st.write(start_time)


