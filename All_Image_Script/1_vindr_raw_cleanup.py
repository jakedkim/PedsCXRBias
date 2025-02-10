
"""
Created on Tue Sep 27 17:16:00 2022

@author: jakekim

Simple script to pull metadata tags from VinDr dicom files and add data from to associated csv files.

***NOTE: ALL IMAGES ARE PA VIEW****

"""

#Standard import
import os
import pydicom 
import pandas as pd 
import numpy as np

#parent path
image_source = ('/srv/store/jkim/peds_cxr/')  # edit this. this is where images are located.
parent = ('/home/jkim/research/peds_cxr/') # edit this. this is the parent folder. 
vindr_source = (image_source + 'VinDR_PCXR_Peds_Chest_X-Ray_Data/vindr-pcxr-an-open-large-scale-pediatric-chest-x-ray-dataset-for-interpretation-of-common-thoracic-diseases-1.0.0/')
metadata_output = (parent + 'peds_cxr_metadata/raw_metadata/')

#file paths
test_annot = (vindr_source + 'annotations_test.csv')
train_annot = (vindr_source + 'annotations_train.csv')
test_labels = (vindr_source + 'image_labels_test.csv')
train_labels = (vindr_source + 'image_labels_train.csv')

#create a dataframe of the values in the listed csvs
train_annot_df = pd.read_csv(train_annot)
test_annot_df = pd.read_csv(test_annot)
train_labels_df = pd.read_csv(train_labels)
test_labels_df = pd.read_csv(test_labels)

#annotations dataframe
image_annotations_df = pd.concat([train_annot_df, test_annot_df])
image_annotations_df.set_index('image_id',inplace=True)

#labels dataframe
train_labels_df.insert(0,'Set','train')
test_labels_df.insert(0,'Set','test')

image_labels_df = pd.concat([train_labels_df, test_labels_df])
image_labels_df.set_index('image_id',inplace=True)

image_labels_df['Patient_age'] = np.nan #create column for patient age
image_labels_df['Patient_sex'] = np.nan #create column for patient sex

#create a list of all file names found in the train and test folders
test_path = (vindr_source + 'test')
train_path = (vindr_source + 'train')

train_images = os.listdir(train_path)
test_images = os.listdir(test_path)

images = train_images + test_images #make one list of image ids

#create dictionary of image ids and labels from labels csv
image_dict = image_labels_df.to_dict('index')

local_labels = image_annotations_df.class_name.unique()
local_labels = local_labels.tolist()

#add labels from annotation csv
for i in image_dict:
    for label in local_labels:
        image_dict[i][label] = np.nan

for i in image_dict:
    #add new labels with binary code taken from the annotation file
    print('image: ',i)
    for label in local_labels:
        print('*****label******: ',label)
        var = image_annotations_df.loc[i,'class_name']
        if type(var) == str:
            if var == label:
                image_dict[i][label] = 1.0
                print('label matches')
            if var != label:
                image_dict[i][label] = 0.0
                print('no')
        else: 
            var.tolist()
            print(var)
            for x in var:
                print('var: ',x)
                if x == label:
                    image_dict[i][label] = 1.0
                    print('label matches')
                if x != label:
                    if image_dict[i][label] == 1.0:
                        continue
                    if image_dict[i][label] != 1.0:
                        image_dict[i][label] = 0.0
                        print('does not match')
    #add patient age and sex to the columns
    set_lab = image_dict[i]['Set']
    print(set_lab)
    if set_lab == 'train':
        print('train')
        im_path = train_path + '/' + i + '.dicom'
        image = pydicom.dcmread(im_path)
        try:
            age = image.PatientAge
        except AttributeError:
            age = 'missing!'
        try:
           sex = image.PatientSex
        except AttributeError:
           sex = 'missing!'        
        image_dict[i]['Patient_age'] = age
        image_dict[i]['Patient_sex'] = sex
    elif set_lab == 'test':
        print('test')
        im_path = test_path + '/' + i + '.dicom'
        image = pydicom.dcmread(im_path)
        try:
            age = image.PatientAge
        except AttributeError:
            age = 'missing!'
        try:
           sex = image.PatientSex
        except AttributeError:
           sex = 'missing!'        
        image_dict[i]['Patient_age'] = age
        image_dict[i]['Patient_sex'] = sex    

#create new dataframe
final_df = pd.DataFrame.from_dict(image_dict, orient='index')

#relist ages listed in days and months to years
final_df['Patient_age_year'] = np.where(final_df['Patient_age'].str.contains('D|M'), '000Y', final_df['Patient_age'])
final_df['Patient_age_year'] = final_df['Patient_age_year'].astype(str)

for i in range(0, len(image_labels_df)):
    final_df['Patient_age_year'] = final_df['Patient_age_year'].str[:3]
    final_df['Patient_age_year'] = final_df['Patient_age_year'].astype(str)

# list the valiues
for col in final_df:
    print(final_df[col].value_counts().sort_values(ascending=False))

#reorder final dataframe
final_df = final_df.loc[:,['Set','rad_ID','Patient_age','Patient_sex','Patient_age_year','No finding','Bronchitis','Brocho-pneumonia','Other disease','Bronchiolitis','Situs inversus','Pneumonia','Pleuro-pneumonia','Diagphramatic hernia','Tuberculosis','Congenital emphysema','CPAM','Hyaline membrane disease','Mediastinal tumor','Lung tumor','Boot-shaped heart','Peribronchovascular interstitial opacity','Reticulonodular opacity','Bronchial thickening','Enlarged PA','Cardiomegaly','Diffuse aveolar opacity','Other opacity','Other lesion','Consolidation','Mediastinal shift','Anterior mediastinal mass','Dextro cardia','Pleural effusion','Stomach on the right side','Atelectasis','Lung hyperinflation','Egg on string sign','Interstitial lung disease - ILD','Infiltration','Lung cavity','Pneumothorax','Edema','Pleural thickening','Other nodule/mass','Clavicle fracture','Chest wall mass','Lung cyst','Emphysema','Bronchectasis','Expanded edges of the anterior ribs','Pulmonary fibrosis','Paraveterbral mass','Aortic enlargement','Calcification','Intrathoracic digestive structure']]

final_df.reset_index(level=0, inplace=True)
final_df.rename(columns={final_df.columns[0]: 'image_id'}, inplace=True)

#%% Send out to csv
final_df.to_csv(metadata_output + 'vindr_raw_metadata_jk.csv', index=False)


# counting number of labels per disease by patient gender 
total = final_df.sum(numeric_only=True)
total.to_csv(metadata_output + 'vindr_counts.csv')