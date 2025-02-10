"""
Created on Tue Sep 27 17:16:00 2022

@author: seangarin & jakekim

Simple script to pull metadata tags from dicom files, then add them to csv files.

Pull metadata from DICOMS or CSVs, categorize
"""

#Standard import
import os
import pydicom 
import pandas as pd 
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

#Paths
image_source = ('/srv/store/jkim/peds_cxr/')
parent = ('/home/jkim/research/peds_cxr/')
labels_path = (image_source + 'NIH_Peds/NIH-CXR-14/metadata.csv')
output = (parent + 'peds_cxr_metadata/raw_metadata/') 

#create a dataframe of the values in the listed csv 
labels_df = pd.read_csv(labels_path)

labels_df.set_index('Image Index',inplace=True)

#%%
sex_list = ['M','F']
age_list = ['0','1','2','3','4','5','6','7','8','9','10','11','12','13','14','15','16','17']

final_df = labels_df
final_df['Patient Age'] = final_df['Patient Age'].astype(str)

final_df = labels_df.loc[(labels_df['Patient Gender'].isin(sex_list)) & (labels_df['Patient Age'].isin(age_list))]

#%%
print(final_df['Patient Gender'].value_counts().sort_values())
print(final_df['Patient Age'].value_counts().sort_index())
print(final_df['View Position'].value_counts().sort_index())

#%% Send out to csv
final_df.to_csv(output + 'nih_raw_metadata_jk.csv')

# counting number of labels per disease by patient gender 
grouped = final_df.groupby('Patient Gender').sum().reset_index()
total = final_df.sum(numeric_only=True).rename('All')
summary = grouped.append(total)
summary = summary.transpose()
summary.to_csv(output + 'nih_counts.csv')




