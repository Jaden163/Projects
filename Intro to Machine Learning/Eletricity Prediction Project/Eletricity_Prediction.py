import pandas as pd
import csv
import sys
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.tree import export_graphviz
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
import requests
import json
from datetime import datetime
from influxdb import DataFrameClient, InfluxDBClient
import argparse
import os


#email=sys.argv[1]



#could be improved significantly by parsing to dictionary rather than list : Less iterations and faster search speed




#Reading and cleaning downloaded csv

def utility_api_search(email):
    
    #INPUT: Type:String - client's email address 
    #OUTPUT: Type:String - download link for client's bill in CSV ; error exception if email can not be found
    
    utility = requests.get('https://utilityapi.com/api/v2/authorizations?access_token=68717b7708024b608ceb27455530a613')
    utility_d = json.loads(utility.text)
    for users in utility_d['authorizations']:
        if (users['customer_email']==email and users['utility']=="ConEd"):
            print(users['exports_list'][0]['link'])
            return users['exports_list'][0]['link']
        
    raise Exception ('Invalid Email')
            
def download_CSV(CSV_link):
    
    #INPUT: Type:String - CSV download link for client's bill
    #OUTPUT: Type:List - List generated from parsing the CSV file
    
    with requests.Session() as s:
        download = s.get(CSV_link+'&access_token=68717b7708024b608ceb27455530a613')
        decoded_content = download.content.decode('utf-8')
        cr = csv.reader(decoded_content.splitlines(), delimiter=',')
        my_list = list(cr)
        return my_list

def clean_data(CSV_list):
    
    #INPUT: Type:List - List generated from parsing CSV file
    #OUTPUT: Type:List - Cleaned up data by deleting ConEd's uncessary deta and outliers 

    cost=[]
    for line in (CSV_list):
        cost.append(line[11])
        for column in range(6):
            del line[0]
        line.pop()
        for column in range(5):
            del line[3]
    
    outliers=[]
    nulldata=[]
    for i in range(1,len(CSV_list)):
        if int(float(CSV_list[i][2]))>40:
            outliers.append(CSV_list[i])
        elif int(float(CSV_list[i][3]))==0 or CSV_list[i][3]=='null':
            nulldata.append(CSV_list[i])


    for i in outliers:
        CSV_list.remove(i)
    
    for line in (CSV_list):
        for column in range(2):
            del line[1]

    return cost
                     
def add_zero(string_num):
    if len(string_num)==1:
        string_num='0'+string_num
    return string_num

def year_convert(string_num):
    string_num="20"+string_num
    return string_num
 
def change_date_format(CSV_list):
    for line in CSV_list:
        if line[0]=="bill_start_date":
            line[0]='year'
            line.insert(1,'month')
            line.insert(2,'day')      
        else:
            parse_date=line[0].split("/")
            month=add_zero(parse_date[0])
            year=parse_date[2]
            day=add_zero(parse_date[1])
            line[0]=year
            line.insert(1,month)
            line.insert(2,day)
            
            
#using NOAA api to get AVG temp and writing to CSV List   

def collect_AVGTEMP(CSV_list,token='PehOkavrRldfKzYJPfOYdNhSqKgJyMPw',station_id='GHCND:USW00014732'):
    
    newest_date=CSV_list[1]
    month=newest_date[1]
    day=newest_date[2]
    year=newest_date[0]
    newest_date=year+'-'+month+'-'+day

    oldest_date=CSV_list[len(CSV_list)-1]
    month=add_zero(str(int(oldest_date[1])-1))
    day=oldest_date[2]
    year=oldest_date[0]
    oldest_date=year+'-'+month+'-'+day
    
    #3-month prediction data
    start_date=str(int(CSV_list[1][0])-1)+'-12-01'
    end_date='2014-01-01'
    diff_years=int(CSV_list[1][0])-2014
    current_month=int(CSV_list[1][1])
    prediction = requests.get('https://www.ncdc.noaa.gov/cdo-web/api/v2/data?datasetid=GSOM&datatypeid=TAVG&limit=1000&stationid='+station_id+'&startdate='+end_date+'&enddate='+start_date+'&units=standard',headers={'token':token})
    pre_d=json.loads(prediction.text)
    
    predict_temp=[0,0,0]
    total=len(pre_d['results'])
    
    for i in range(1,diff_years+1):
        for j in range(3):
            result=(pre_d['results'][total-i*12+current_month+j])
            predict_temp[j]+=result['value']

    for i in range(3):
        predict_temp[i]=predict_temp[i]/diff_years
        
    #loading result from calling weather api
    result = requests.get('https://www.ncdc.noaa.gov/cdo-web/api/v2/data?datasetid=GSOM&datatypeid=TAVG&limit=1000&stationid='+station_id+'&startdate='+oldest_date+'&enddate='+newest_date+'&units=standard',headers={'token':token})
    d = json.loads(result.text)
    
    #append AVGTEMP header
    CSV_list[0].append("AVGTEMP")

    csv_iter=1
    for i in reversed(d['results']):
        date_time=(i['date'])
        date_time=datetime.strptime(date_time, '%Y-%m-%dT%H:%M:%S')
        date_time = date_time.strftime("%m/%d/%Y")
        date_time=(date_time.split("/"))
        iter_month=add_zero(date_time[0])
        iter_year=(date_time[2])
        lines=CSV_list[csv_iter]

        if (iter_month==lines[1] and iter_year==lines[0]):
            lines.append(str(i['value']))
            csv_iter+=1

        if csv_iter>(len(CSV_list)-1):
            break
            
    return predict_temp

def CSV_write(CSV_list,email):
    file_name=email+'.csv'
    clean_file=open(file_name,"w")
    for i in CSV_list:
        line=",".join(i)
        print(line,file=clean_file)
    clean_file.close()
    return file_name

def random_forest_predict(CSV_file_name,predict_temp):
    predict_volume=[0,0,0]
    random_forest=pd.read_csv(CSV_file_name)
    random_forest=random_forest.drop(['year','month','day'],axis=1)
    labels = np.array(random_forest['bill_volume'])
    random_forest= random_forest.drop('bill_volume', axis = 1)
    random_forest = np.array(random_forest)
    train_features, test_features, train_labels, test_labels = train_test_split(random_forest, labels, test_size = 0.1, random_state = 42)
    rf = RandomForestRegressor(n_estimators = 1000, random_state = 42)
    rf.fit(train_features, train_labels);
    for i in range(3):
        predict_volume[i]=int(rf.predict([[predict_temp[i]]]))
    return predict_volume

def linear_regression_predict(CSV_file_name,predict_temp):
    predict_volume=[0,0,0]
    data=pd.read_csv(CSV_file_name)
    data=data.drop(['year','month','day'],axis=1)
    X = data.drop('bill_volume', axis=1)
    y = data[['bill_volume']]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.1, random_state=1)
    regression_model = LinearRegression()
    regression_model.fit(X_train, y_train)
    for i in range(3):
        predict_volume[i]=int(regression_model.predict([[predict_temp[i]]]))
    return predict_volume


def return_date(date):
    if date[5:7]=='12':
        date=date.split('-')
        date[0]=str(int(date[0])+1)
        date[1]='01'
        date='-'.join(date)
    else:
        temp=str(int(date[5:7])+1)
        date=date.split('-')
        date[1]=add_zero(str(temp))
        date='-'.join(date)
    return date

def prev_year(date):
    date=date.split('-')
    date[0]=str(int(date[0])-1)
    date='-'.join(date)
    return date



def database_format(CSV_file_name,predict_volume,predict_temp,fill_data):
    data=[]

    CSV_file=open(CSV_file_name,'r')
    for line in CSV_file:
        line=line.split(",")
        data.append(line)
    CSV_file.close()

    for i in range(len(data)):
        data[i][4]=data[i][4].strip("\n")
        if i==0:
            data[i][0]='bill_start_date'
            data[i][1]=fill_data[0]
            del data[i][2]
        else:
            date=data[i][0]+"-"+data[i][1]+'-'+data[i][2]+'T00:00:00'
            data[i][0]=date
            data[i][1]=fill_data[i]
            del data[i][2]

    first=['date','0','0','0']
    second=['date','0','0','0']
    third=['date','0','0','0']
    predict_data=[]
    predict_data.append(first)
    predict_data.append(second)
    predict_data.append(third)

    newest_date=data[1][0]
    for i in range(3):
        newest_date=return_date(newest_date)
        predict_data[i][0]=newest_date
        predict_data[i][3]=str(predict_temp[i])
        predict_data[i][2]=str(predict_volume[i])
        data.append(predict_data[i])

    dict={}

    for i in (data):
        line=i[0].split("-")
        if len(line)!=1:
            key=line[0]+'-'+line[1]
            dict[key]=i[2]

    for i in range(len(data)):
        if i==0:
            data[i].append("prev_vol")
        else:
            search=data[i][0].split('-')
            search=search[0]+'-'+search[1]
            value=dict.get(prev_year(search))
            if value==None:
                data[i].append('0')
            else:
                data[i].append(value)


    CSV_write(data,email)

def model_AVG(RF,LR):
    AVG=[0,0,0]
    print(RF)
    print(LR)
    for i in range(3):
        AVG[i]=(RF[i]+LR[i])/2
    print(AVG)
    return AVG




utility_api_result=utility_api_search(email)
CSV_result=download_CSV(utility_api_result)
fill_data=clean_data(CSV_result)
change_date_format(CSV_result)
predict_temp=collect_AVGTEMP(CSV_result)
cleaned_file=CSV_write(CSV_result,email)
predict_volume_RF=random_forest_predict(cleaned_file,predict_temp)
predict_volume_LR=linear_regression_predict(cleaned_file,predict_temp)
predict_volume_AVG=model_AVG(predict_volume_RF,predict_volume_LR)

database_format(cleaned_file,predict_volume_AVG,predict_temp,fill_data)


client = InfluxDBClient('localhost', 8086)
client.switch_database('idk')
database_name=email+'db'

client.drop_measurement(database_name)

def read_data(filename):
    with open(filename) as f:
        lines = f.readlines()[1:]
    return lines

filename = email+'.csv'
lines = read_data(filename)

for rawline in lines:
        line = rawline.split(",")
        date=(line[0]).split('-')
        year=int(date[0])
        month=int(date[1])
        day=int(date[2].split("T")[0])
        epoch=int(datetime(year,month,day,0,0).timestamp())
        epoch=epoch*1000
        line[3]=line[3].strip('\n')
        line[4]=line[4].strip('\n')
        json_body1 = [
        {
            "measurement": database_name,
            'time':epoch,
            "fields": {
                "TAVG": line[3],
                "bill": 'ConEd',
                "bill_state_date":line[0],
                "bill_total_cost": float(line[1]),
                "user":email,
                "bill_total_volume": float(line[2]),
                'prev_yr_vol':line[4]
            }
        }
        ]
        client.write_points(json_body1,"ms")



