# -*- coding: utf-8 -*-
"""
Started on Thu Jun 17 17:49:14 2021

@author: Dmitry Kuzyurin
"""
import pandas as pd
import requests
import re
import sys
import os
from bs4 import BeautifulSoup
from selenium import webdriver
from time import sleep
from datetime import datetime
from progress.bar import IncrementalBar

def get_html(url, params=None):
    HEADERS = { 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.101 Safari/537.36',
            'accept': '*/*'}
    r = requests.get(url, headers=HEADERS, params=params)
    return r

def get_cards_from_list(html_text):
    DOMAIN = 'https://www.wildberries.ru'
    soup = BeautifulSoup(html_text, 'html.parser')
    items = soup.find_all('div', class_='dtList')
    cards = []
    for item in items:
        price_info = item.find('span', class_='price').get_text(strip=True) \
            .replace('\xa0', '').split('₽')
        review_info = item.find('span', class_='c-stars-line-lg')
        lnk = DOMAIN + item.find('a', class_='ref_goods_n_p') \
                          .get('href').split('?')[0]
        cards.append({'id': lnk.split('/')[-2],
                      'title': item.find('span', class_='goods-name') \
                          .get_text(strip=True),
                      'link': lnk,
                      'base_price': price_info[0] if len(price_info) <3 \
                              else price_info[1],
                      'actual_price': price_info[0],
                      'discount': 0 if len(price_info) < 3 else price_info[2][:-1],
                      'rating': 0 if review_info is None else review_info \
                          .get('class')[-1][-1],
                      'reviews_count': 0 if review_info is None else item \
                          .find('span', class_='dtList-comments-count') \
                          .get_text(strip=True)
                    })       
    return cards

def is_next_page(html_text):
    soup = BeautifulSoup(html_text, 'html.parser')
    if soup.find('a', class_='pagination-next'):
        return soup.find('a', class_='pagination-next').get('href').split('?')[1]
    return None
    
def parse_catalogue(path, cat_dataset_path):
    items_list = []
    para = None
    page_number = 0
    while True:
        html_obj = get_html(path, para)
        if html_obj.status_code == 200:
            page_number += 1
            print("Parsing page #{}...".format(page_number), end='')
            cont = get_cards_from_list(html_obj.text)
            items_list.extend(cont)
            print("OK")
        else:
            print("Error parsing URL {}".format(path))
            break
        para = is_next_page(html_obj.text)
        if para is None:
            break                   
    items_df = pd.DataFrame(items_list)
    items_df.to_csv(cat_dataset_path, index=False)
    print("\nParsing catalogue finished:\n{}".format(path))
    print("\nDataFrame file saved:\n{}\n".format(cat_dataset_path))

def get_int_para(src_str, para_name):
    try:
        # Looking for a substr like '"ordersCount":13'
        sc = re.search(para_name + r'\s*\"\s*:\s*(\d+)', src_str)
        return int(sc.groups()[0])
    except:
        return None
    
def get_str_para(src_str, para_name):
    try:
        # Looking for a substr like '"supplierName":"Индивидуальный предприниматель Шедеви Андрей Геннадьевич"'
        sc = re.search(para_name + r'\":\"(.+?)\",', src_str)
        return (sc.groups()[0])
    except:
        return None

def get_first_review_date(driver, url, rev_count):
    driver.get(url)
    element = driver.find_element_by_class_name('new-post-add')
    element.location_once_scrolled_into_view
    # Waiting for the element 'sort_select' appears and clicking it
    # for sorting reviews in order of Date ascending
    if rev_count > 1:
        for attempt in range(0, 5):
            try:
                sleep(1)
                element = driver.find_element_by_class_name('sort_select')
                break
            except:
                continue
        if element is None:
            return None
        else:
            element.click()
    else:
        sleep(1)
    try:
        date_elem = driver.find_element_by_class_name('time')
        # "content" is a string like '2020-05-28T08:27:51.684017959Z'
        return date_elem.get_attribute("content").split('T')[0]
    except:
        return None

def save_image(id, img_path, out_img_path):
    p = requests.get(img_path)
    if p.status_code != 200:
        print("Error reading image: {}".format(img_path))
        return
    out_path = out_img_path + id + '.jpg'
    out = open(out_path, "wb")
    out.write(p.content)
    out.close()

def parse_one_card(url, driver, rev_count, images_path):
    html_obj = get_html(url)
    if html_obj.status_code == 200:
        html_text = html_obj.text
        soup = BeautifulSoup(html_text, 'html.parser')
        descr = str(soup.find('div', class_='j-description').get_text())
        features = soup.find('div', class_='params').find_all('div', class_='pp')
        id = url.split('/')[-2]
        first_img_path = soup.find("meta", attrs={'property': 'og:image'})["content"]
        save_image(id, first_img_path, images_path)
        card_features = []
        for feature in features:
            card_features.append(feature.b.get_text().strip())
        data = soup.find_all('script')
        if rev_count:            
            dt = get_first_review_date(driver, url, rev_count)
            if dt is None:
                print("Error getting first review date, URL {}".format(url))
        for script_src in data:
            script_str = str(script_src)
            pos = script_str.find('ordersCount')
            if pos > -1:
                return {'id': id,
                        'orders_count': get_int_para(script_str, 'ordersCount'),
                        'brand': soup.find('span', class_='brand').get_text(),
                        'seller': get_str_para(script_str, 'supplierName'),
                        'images_count': len(soup.find('div', class_='j-sw-images-carousel').find_all('img')),
                        'video': int(soup.find('span', class_='video-thumb-placeholder') is not None),
                        'description': descr.strip(),
                        'features': card_features,
                        'first_date': dt if rev_count else None }
    print("Error parsing card {}".format(url))
    return None

def parse_all_cards(path, cat_dataset_path, items_dataset_path, \
                    images_path, is_restore):
    fold_size = 50
    cards_data = []
    items_df = pd.read_csv(cat_dataset_path)
    if is_restore:
        cards_saved_df = pd.read_csv(items_dataset_path)
        saved_count = cards_saved_df.shape[0]       
    options = webdriver.ChromeOptions()
    options.add_argument('--log-level=3')
    driver = webdriver.Chrome(options=options)
    cards_count = len(items_df)
    bar = IncrementalBar('Parsing cards', max = cards_count)
    for index, row in items_df.iterrows():
        bar.next()
        if is_restore and index < saved_count:
            continue            
        cards_data.append(parse_one_card(row['link'], driver, \
                                         row['reviews_count'], images_path))
        if fold_size and not((index+1) % fold_size):
            df_to_save = pd.DataFrame(cards_data) if not is_restore \
                else cards_saved_df.append(pd.DataFrame(cards_data))
            df_to_save.to_csv(items_dataset_path)      
        #if index == 10:
        #    break        #Убрать
    cards_df = pd.DataFrame(cards_data) if not is_restore \
        else cards_saved_df.append(pd.DataFrame(cards_data))        
    cards_df.to_csv(items_dataset_path)
    bar.finish()
    print("Cards parsing finished successfully")


def err_exit(error_type):
    err_msg = [ "USE python wbparse.py [-cat | -items | -restore] category_path",
                "Category Path expected",
                "Too many arguments",
                "Wrong flag" ]
    print("ERROR: {}\n{}".format(err_msg[error_type], err_msg[0]))
    sys.exit()
       

if __name__ == "__main__":
    flags = ['-cat', '-items', '-restore']
    err_type = 1 if len(sys.argv) < 2 else \
               2 if len(sys.argv) > 3 else \
               3 if len(sys.argv) == 3 and sys.argv[1] not in flags else 0
    if(err_type):
        err_exit(err_type)
    cat_path = sys.argv[-1]  
    out_path = cat_path.split('/')[-1] + '_' + cat_path.split('/')[-2] + '\\'
    images_path = out_path + 'images\\'
    cat_dataset_file = out_path + 'cat.csv'
    today = datetime.today().strftime('%Y-%m-%d')
    items_dataset_file = out_path + 'items_' + today + '.csv'
    if sys.argv[-2] not in flags[1:]:
        if not os.access(out_path, os.W_OK):
            os.mkdir(out_path)
        parse_catalogue(cat_path, cat_dataset_file)        
    if sys.argv[-2] in flags[1:]:
        if not os.access(images_path, os.W_OK):
            os.mkdir(images_path)
        parse_all_cards(cat_path, cat_dataset_file, items_dataset_file, \
                        images_path, sys.argv[-2] == flags[2])
