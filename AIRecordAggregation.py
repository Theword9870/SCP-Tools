import requests
import bs4
import re
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime as dt
import asyncio
import httpx
from dataclasses import dataclass
# fake_useragent rotates browser User-Agent strings to avoid bot detection
try:
  import fake_useragent
except ImportError:
  print("Warning: fake_useragent is reccomended but not nessasarry")

# Base URL for the AI-related forum category on 05command wikidot
AI = "https://05command.wikidot.com/forum/c-7852401/p/1"


async def get_page(client, url, sem):
  """Fetch a single page asynchronously, respecting the concurrency semaphore."""
  async with sem:  # limit concurrent requests to avoid overloading the server
    try:
      ua = fake_useragent.UserAgent()
      headers = {'User-Agent': ua.random}  # use a random browser User-Agent
    except ModuleNotFoundError:
      headers = {'User-Agent': 'python-httpx/x.y.z'}  # fallback if fake_useragent not installed
    response = await client.get(url, headers=headers)
    print(f'Fetched {url}')
  return response


def get_last_page(url):
  """Scrape the forum index page to find the total number of pages."""
  body = requests.get(url)
  soup = bs4.BeautifulSoup(body.text, 'html.parser')
  lastpage = soup.find('div', class_='pager')
  lastpage = lastpage.find('span', class_='pager-no').text.strip()  # type: ignore
  # Text looks like "page 1 of 42" — strip prefix to get the count
  return int(lastpage.strip('page 1 of '))


# Determine total page count before scraping
pageNum = get_last_page(AI)

@dataclass
class data:
  rowlist: list
  authorlist: list
  datelist_unix: list
  postlist:list

async def scrape_pages(id='7852401') -> data:
  """Fetch and parse all forum pages concurrently."""
  
  # lists that parse_page populates as pages are processed
  rowlist = []
  # datelist = []          # human-readable dates (unused, kept for reference)
  authorlist = []
  datelist_unix = []       # post timestamps as Python datetime objects
  postlist = []            # reply counts per thread

  async def parse_page(page, pages):
    """Extract thread dates, authors, and post counts from a single forum page."""
    soup = bs4.BeautifulSoup(page.text, 'html.parser')
    main_content = soup.find('div', id='page-content')
    table = main_content.find('table')  # type: ignore
    rows = table.find_all('tr', class_='')  # type: ignore  — grab all data rows (no special class)

    for row in rows:
      # dates = row.find('span', class_='odate').text  
      # datelist.append(dates)
      # The odate span encodes the Unix timestamp in its second CSS class, e.g. "time_1234567890"
      datelist_unix.append(
        dt.fromtimestamp(int(row.find('span', class_='odate').get('class')[1].strip("time_")))  # type: ignore
      )

      # Author name lives in the second <a> inside the printuser span
      author = row.find('td', class_='started').find('span', class_='printuser').find_all('a')  # type: ignore
      author = author[1].text
      authorlist.append(author)

      # Post count for this thread
      posts = row.find('td', class_='posts').text.strip() # type: ignore
      postlist.append(posts)

    rowlist.append(rows)
    print(f"Page {pages.index(page)+1} done.")

  
  urls = [f'https://05command.wikidot.com/forum/c-{id}/p/{x}' for x in range(1, pageNum + 1)]
  sem = asyncio.Semaphore(7)  # cap at 7 simultaneous requests — wikidot drops TLS handshakes beyond this
  async with httpx.AsyncClient() as client:
    tasks = [get_page(client, url, sem) for url in urls]
    pages = await asyncio.gather(*tasks)   # fetch all pages in parallel
    tasks = [parse_page(page, pages) for page in pages]
    await asyncio.gather(*tasks)           # parse all pages in parallel
    return data(rowlist,authorlist,datelist_unix,postlist)


aipages = asyncio.run(scrape_pages())
# print(datelist_unix)
print()
# print(authorlist)
# all_dates = np.array([dt.strptime(x, r'%d %b %Y %H:%M') for x in datelist]) #convert to datetime
# Convert collected lists to numpy arrays for easier manipulation
all_dates = np.array(aipages.datelist_unix)
all_authors = np.array(aipages.authorlist)

# Pair each post date with its author, then sort chronologically
date_author = np.stack((all_dates, all_authors), axis=1)
date_author = date_author[date_author[:, 0].argsort()]

# Collapse each date to the first of its month to bucket threads by month
unique_months = np.unique(
  np.array([x.replace(hour=0, minute=0, second=0, microsecond=0, day=1) for x in all_dates.copy()]),
  return_counts=True
)

# Count threads per author
unique_authors = np.unique(all_authors, return_counts=True)

print(unique_authors)
print(unique_months)
for month in unique_months[0]:
  print(month.strftime("%b %Y"))

# --- Figure 1: Thread count over time (by month) ---
plt.figure(1, figsize=(15, 5))

#trend line stuff
coefficients = np.polyfit(mdates.date2num(unique_months[0]), unique_months[1], 1)
polynomial = np.poly1d(coefficients)
trendline_values = polynomial(mdates.date2num(unique_months[0]))
plt.plot(unique_months[0], trendline_values, linestyle="--", color='#cfcfcf',linewidth=2, label="Trend Line")

#dates
dates = plt.plot(unique_months[0], unique_months[1], label="AI records")
plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))  # human-readable month labels
plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=1))  # tick every 1 months
plt.gcf().autofmt_xdate()  # rotate labels to prevent overlap


# Mark when the AI ban became permanent
plt.axvline(x=dt(2025, 10, 1), color='r', linestyle='--', label="AI is now Perma")  # type: ignore
plt.legend()
plt.grid()
plt.savefig('graph.png', dpi=300)
print("file saved as graph.png")

# --- Figure 2: Pie chart of threads per author ---
plt.figure(2, figsize=(10, 5))
other_count = 0

# Build a list of [author, count] pairs
unique_authors_trimmed = np.vstack((unique_authors[0], unique_authors[1])).T.tolist()
# unique_authors_trimmed = [list(x) for x in  list(zip(unique_authors[0],unique_authors[1]))]

# Lump authors with 10 or fewer threads into an "Other" slice
other_count = sum(int(count) for author, count in unique_authors_trimmed if int(count) <= 10)
unique_authors_trimmed = [[author, count] for author, count in unique_authors_trimmed if int(count) > 10]
unique_authors_trimmed.append(["Other", other_count])

print()
print(unique_authors_trimmed)
plt.pie(
  [x[1] for x in unique_authors_trimmed],
  labels=[x[0] for x in unique_authors_trimmed],
  autopct='%1.1f%%',
  radius=1.5,
  pctdistance=0.7
)
plt.savefig('pie.png', dpi=300)
print('flie saved as pie.png')

# --- Figure 3: Thread activity by hour of day (UTC) ---
# Normalise every timestamp to the same dummy date so hours are comparable
hours = np.unique(
  np.array([x.replace(year=2000, month=1, day=1, minute=0, second=0) for x in all_dates.copy()]),
  return_counts=True
)
hours = np.vstack((hours[0], hours[1])).T

print(hours)
plt.figure(3, figsize=(10, 5))
plt.plot([x[0] for x in hours], [x[1] for x in hours])
plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=1))
plt.gcf().autofmt_xdate()
plt.grid()
plt.xlabel('Time of day (UTC)')
plt.ylabel('Number of posts')
plt.savefig('hours.png', dpi=300)
print('file saved as hours.png')

# --- Figure 4: Bar chart of reply-count distribution ---
unique_posts = np.unique(np.array(aipages.postlist), return_counts=True)
unique_posts = np.vstack((unique_posts[0], unique_posts[1])).T
unique_posts = sorted(unique_posts, key=lambda x: int(x[0]))

print(unique_posts)

# Group raw reply counts into readable buckets

posts1     = sum(int(count) for post, count in unique_posts if int(post) <= 1)
posts2     = sum(int(count) for post, count in unique_posts if int(post) == 2)
posts3     = sum(int(count) for post, count in unique_posts if int(post) == 3)
posts4to6  = sum(int(count) for post, count in unique_posts if 4 <= int(post) <= 6)
posts7to9  = sum(int(count) for post, count in unique_posts if 7 <= int(post) <= 9)
plus_ten   = sum(int(count) for post, count in unique_posts if int(post) >= 10)

adj_unique_posts = [
  ["1",    posts1],
  ["2",    posts2],
  ["3",    posts3],
  ["4-6",  posts4to6],
  ["7-9",  posts7to9],
  ["10+",  plus_ten],
]

print(adj_unique_posts)
plt.figure(4, figsize=(7, 7))
plt.bar([x[0] for x in adj_unique_posts], [x[1] for x in adj_unique_posts])
plt.savefig('posts.png', dpi=300)
print("\n\n\ndone")
