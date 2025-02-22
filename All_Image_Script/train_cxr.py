"""Trains CXR model.

Input:
  images: assumes there is a dir at [cfg.data_dir]/[dataset] structured as:
    [dataset]
      images/: contains all image files in any structure
      image_paths.txt: paths from [dataset]/images for each image
      [train file.txt]: list of images to use in train set
      [val file.txt]: list of images to use in val set
      [labels.csv]: table of image names and column for each label (0/1 values)

Args:
  See parser below

Output:
  model state (torch model state): 
    saves [model name]_model.pt to [results-dir], taken at best epoch
    
  model stats (dict): 
    saves [model name]_stats.pt to [results-dir], taken at best epoch
    Structure:
      {
        epoch: int
        loss: {
          train: list of floats
          val: list of floats
        }
        auc: {
          train: list of floats
          val: list of floats
        }
        points: {
          train: {
            y: list of ints
            yhat: list of floats
          }
          val: {
            y: list of ints
            yhat: list of floats
          }s
        }
        timer: list of floats
      }
    
  run stats log: prints stats to [results_dir]/results.csv

"""


# Standard
import os, sys, shutil, json
import pandas as pd
import numpy as np
import time
import argparse
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# Parse args
parser = argparse.ArgumentParser()
parser.add_argument("--cfg-dir", default='/cis/home/zmurphy/code/transformer-radiographs/cfg.json', type=str, help='path to cfg.json; using data_dir, labels set')
parser.add_argument("--architecture", default='', type=str, help='selects architecture (DenseNet121/DeiT_B/DeiT_Ti/ResNet152/EfficientNet_B7)')
parser.add_argument("--pretrained", default='y', type=str, help='use pretrained model (y/n)')
parser.add_argument("--labels-set", default='chexnet-14-standard', type=str, help='labels set to use in cfg')
parser.add_argument("--frozen", default='n', type=str, help='freeze all but task head (y/n)')
parser.add_argument("--initial-lr", default=1e-2, type=float, help='initial learning rate')
parser.add_argument("--batch-size", default=16, type=int, help='batch size')
parser.add_argument("--max-epochs", default=50, type=int, help='stop training after this many epochs')
parser.add_argument("--optimizer-family", default='SGD', type=str, help='optimizer to use (SGD/AdamW)')
parser.add_argument("--weight-decay", default=1e-4, type=float, help='weight decay')
parser.add_argument("--momentum", default=0.9, type=float, help='momentum')
parser.add_argument("--scheduler-family", default='step', type=str, help='selects scheduler family (step/drop)')
parser.add_argument("--drop-factor", default=0.1, type=float, help='drop factor for scheduler')
parser.add_argument("--plateau-patience", default=3, type=int, help='number of epochs to wait for improvement for scehduler')
parser.add_argument("--plateau-threshold", default=1e-4, type=float, help='minimum change to count as improvement')
parser.add_argument("--break-patience", default=5, type=int, help='number of epochs to wait for improvement before stopping training')
parser.add_argument("--dataset", default='nihcxr14', type=str, help='selects dataset (nihcxr14/chexpert/padchest/mimic)')
parser.add_argument("--train-file", default='train_100.txt', type=str, help='name of txt file to use as training list')
parser.add_argument("--val-file", default='val_100.txt', type=str, help='name of txt file to use as val list')
parser.add_argument("--use-parallel", default='y', type=str, help='***')
parser.add_argument("--train-transform", default='hflip', type=str, help='selects transforms to use in training (hflip/***)')
parser.add_argument("--num-workers", default=12, type=int, help='number of dataloader workers')
parser.add_argument("--fold", default=0, type=int, help='id variable for fold number')
parser.add_argument("--norm-layer", default='batch', type=str, help='which norm layer to use (ViT->layer, CNN-> batch)')
parser.add_argument("--dropout", default=0, type=float, help='dropout')
parser.add_argument("--use-mixup", default='n', type=str, help='use mixup/cutmix augmentation')
parser.add_argument("--image-size", default=224, type=int, help='image size to use')
parser.add_argument("--print-batches", default='n', type=str, help='print batch updates')
parser.add_argument("--scratch-dir", default='~/scratch', type=str, help='scratch dir for tmp files')
parser.add_argument("--results-dir", default='/export/gaon1/data/zmurphy/transformer-cxr/results', type=str, help='directory to save results')
parser.add_argument("--use-gpus", default='all', type=str, help='gpu ids (comma separated list eg "0,1" or "all")')
args = parser.parse_args()

"""General setup"""
# Set GPU vis
if args.use_gpus != 'all':
    os.environ['CUDA_DEVICE_ORDER']='PCI_BUS_ID'
    os.environ['CUDA_VISIBLE_DEVICES']=args.use_gpus

# PyTorch
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import torchvision
from torchvision import transforms
from sklearn.metrics import roc_auc_score

# Custom
import custom_modules as CXR

# Get cfg
with open(args.cfg_dir.replace('~', os.path.expanduser('~')), 'r') as f:
    cfg = json.load(f)
cfg['data_dir'] = cfg['data_dir'].replace('~', os.path.expanduser('~'))

# Parse args
args.pretrained = args.pretrained == 'y'
labels = []
if args.labels_set == 'chexnet-14-standard':
    labels = cfg['labels_chexnet_14_standard']
elif args.labels_set == 'mura-standard':
    labels = cfg['labels_mura_standard']
args.frozen = args.frozen == 'y'
args.use_parallel = args.use_parallel == 'y'
args.use_mixup = args.use_mixup == 'y'
args.print_batches = args.print_batches == 'y'
args.scratch_dir = args.scratch_dir.replace('~',os.path.expanduser('~'))
args.results_dir = args.results_dir.replace('~',os.path.expanduser('~'))

# Model params
model_args = {
    'model_type': args.architecture,
    'pretrained': args.pretrained,
    'labels_set': args.labels_set,
    'labels': labels,
    'n_labels': len(labels),
    'frozen': args.frozen,
    'initial_lr': args.initial_lr,
    'batch_size': args.batch_size,
    'max_epochs': args.max_epochs,
    'optimizer_family': args.optimizer_family,
    'weight_decay': args.weight_decay,
    'momentum': args.momentum,
    'scheduler_family': args.scheduler_family,
    'drop_factor': args.drop_factor,
    'plateau_patience': args.plateau_patience,
    'plateau_threshold': args.plateau_threshold,
    'break_patience': args.break_patience,
    'data_dir': cfg['data_dir'],
    'dataset': args.dataset,
    'train_file': args.train_file,
    'val_file': args.val_file,
    'use_parallel': args.use_parallel,
    'train_transform': args.train_transform,
    'num_workers': args.num_workers,
    'fold': args.fold,
    'norm_layer': args.norm_layer,
    'dropout': args.dropout,
    'use_mixup': args.use_mixup,
    'img_size': args.image_size,
    'print_batches': args.print_batches,
    'scratch_dir':args.scratch_dir,
    'results_dir':args.results_dir,
    'results_file': '{}_lr{}_bs{}_opt{}_wd{}_sch_{}_pp{}_bp{}_tr{}_va{}_tf{}_nl{}_do{}_{}.txt'.format(
        args.architecture, args.initial_lr, args.batch_size, args.optimizer_family,
        args.weight_decay, args.scheduler_family, args.plateau_patience, args.break_patience,
        args.train_file, args.val_file, args.train_transform, args.norm_layer, args.dropout, int(time.time()))
}

# Print fxn
def printToResults(to_print,file_name):
    with open(os.path.join(model_args['results_dir'],file_name), 'a') as f:
        f.write(to_print)

print(model_args)

"""Model setup"""
# Setup
model = CXR.get_model(model_args)

# Set dropout
for m in model.modules():
    if isinstance(m, nn.Dropout):
        m.p = model_args['dropout']

# Datasets
dataset_root = os.path.join(model_args['data_dir'], model_args['dataset'])
train_data = CXR.CXRDataset(images_list=os.path.join(dataset_root, model_args['train_file']),
                            dataset=model_args['dataset'],
                            images_dir=os.path.join(dataset_root, 'images'),
                            image_paths=os.path.join(dataset_root, 'image_paths.txt'),
                            labels_file=os.path.join(dataset_root, 'labels.csv'),
                            labels=model_args['labels'],
                            transform=model_args['train_transform'],
                            op='train',
                            img_size=model_args['img_size'])
val_data = CXR.CXRDataset(images_list=os.path.join(dataset_root, model_args['val_file']),
                          dataset=model_args['dataset'],
                          images_dir=os.path.join(dataset_root, 'images'),
                          image_paths=os.path.join(dataset_root, 'image_paths.txt'),
                          labels_file=os.path.join(dataset_root, 'labels.csv'),
                          labels=model_args['labels'],
                          transform='none',
                          op='val',
                          img_size=model_args['img_size'])

# Get device
device = 'cpu'
ncpus = os.cpu_count()
dev_n = ncpus
if torch.cuda.is_available():
    device = 'cuda'
    dev_n = torch.cuda.device_count()
print('Device: {} #: {} #cpus: {}\n'.format(device, dev_n, ncpus))

# Data loaders
trainLoader = DataLoader(train_data, batch_size=model_args['batch_size'],
                         pin_memory=True, shuffle=True,
                         num_workers=model_args['num_workers'])

valLoader = DataLoader(val_data, batch_size=model_args['batch_size'],
                       pin_memory=True, shuffle=True,
                       num_workers=model_args['num_workers'])

# Loss functions
loss_fxn = nn.BCELoss()
soft_loss_fxn = nn.BCELoss()

# Mixup settings
mixup_settings = {
    'mc_prob': 0.5,
    'mixup_alpha': 0.8,
    'cutmix_alpha': 1,
    'cutmix_prob': 0.5,
    'cutmix_thresh': np.random.uniform(size=(model_args['max_epochs'], len(trainLoader)))
}
mixup_settings['cutmix_points'] = []
for e in range(model_args['max_epochs']):
    epoch_points = []
    for b in range(len(trainLoader)):
        epoch_points.append(CXR.getCutmixPoints(mixup_settings))
    mixup_settings['cutmix_points'].append(epoch_points)

# Optimizer
optimizer = None
if model_args['optimizer_family'] == 'SGD':
    optimizer = torch.optim.SGD(
        model.parameters(),
        lr=model_args['initial_lr'],
        momentum=model_args['momentum'],
        weight_decay=model_args['weight_decay']
    )
elif model_args['optimizer_family'] == 'AdamW':
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=model_args['initial_lr'],
        weight_decay=model_args['weight_decay']
    )

# Scheduler
scheduler = None
if model_args['scheduler_family'] == 'step':
    scheduler = torch.optim.lr_scheduler.StepLR(
        optimizer=optimizer,
        step_size=model_args['plateau_patience'],
        gamma=model_args['drop_factor'],
        verbose=False
    )
elif model_args['scheduler_family'] == 'drop':
  scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
    optimizer=optimizer,
    factor=model_args['drop_factor'],
    patience=model_args['plateau_patience'],
    verbose=False
  )

  
"""Train loop"""

# Train logs
best_log = {'epoch': -1,
            'loss': {'train': 999999, 'val': 999999},
            'auc': {'train':0, 'val':0},
            'points': {'train': {'y': [], 'yhat': []}, 'val': {'y': [], 'yhat': []}},
            'timer': 0
            }
train_log = {'epoch': -1,
             'loss': {'train': [], 'val': []},
             'auc': {'train': [], 'val': []},
             'timer': []
             }

if model_args['use_parallel']:
  model = nn.DataParallel(model)

# Model to device
model = model.to(device)

# Epoch loop
for epoch in range(model_args['max_epochs']):
    time_start = time.time()
    train_log['epoch'] = epoch

    # Train
    model.train()

    train_loss = 0
    batch_counter = 0
    train_ys = []
    train_yhats = []

    for x, y in trainLoader:
        if model_args['print_batches']:
            print('\rEpoch {}\t{} batch {}/{}'.format(epoch, 'train', batch_counter, len(trainLoader)))
        batch_counter += 1

        x = x.to(device)
        y = y.to(device)

        loss = None
        if model_args['use_mixup']:
            if x.shape[0] % 2 != 0:
                x = x[:-1, :, :, :]
                y = y[:-1, :]
            x, y = CXR.mixup(x, y, mixup_settings=mixup_settings, epoch=epoch, batch_num=batch_counter - 1,
                             device=device)
            yhat = model(x)
            loss = soft_loss_fxn(yhat, y)
        else:
            yhat = model(x)
            loss = loss_fxn(yhat, y)

        optimizer.zero_grad()
        loss.backward()

        if model_args['optimizer_family'] == 'SPS':
            optimizer.step(loss=loss)
        else:
            optimizer.step()

        with torch.no_grad():
            train_loss += loss.item() / len(trainLoader)
            train_ys.extend(y.to('cpu').numpy().tolist())
            train_yhats.extend(yhat.to('cpu').numpy().tolist())

    # Val
    model.eval()

    val_loss = 0
    batch_counter = 0
    val_ys = []
    val_yhats = []

    # For each batch
    for x, y in valLoader:
        if model_args['print_batches']:
            print('Epoch {}\t{} batch {}/{}'.format(epoch, 'val', batch_counter, len(valLoader)))
        batch_counter += 1
        with torch.no_grad():
            x = x.to(device)
            y = y.to(device)

            yhat = model(x)
            loss = loss_fxn(yhat, y)

            val_loss += loss.item() / len(valLoader)
            val_ys.extend(y.to('cpu').numpy().tolist())
            val_yhats.extend(yhat.to('cpu').numpy().tolist())

    # Add to train_log
    epoch_time = (time.time() - time_start) / 60
    train_log['timer'].append(epoch_time)
    train_log['loss']['train'].append(train_loss)
    train_log['loss']['val'].append(val_loss)

    if model_args['use_mixup']:
        train_log['auc']['train'].append(0)
    else:
        train_log['auc']['train'].append(roc_auc_score(train_ys, train_yhats, average='weighted'))
    train_log['auc']['val'].append(roc_auc_score(val_ys, val_yhats, average='weighted'))

    # Best
    # Update best
    if train_log['auc']['val'][-1] - best_log['auc']['val'] >= model_args['plateau_threshold']:
        # Print
        print('New best!')

        # Update best arg
        best_log = {'epoch': epoch,
                    'loss': {'train': train_loss, 'val': val_loss},
                    'auc': {'train': train_log['auc']['train'][-1], 'val': train_log['auc']['val'][-1]}, 
                    'points': {'train': {'y': train_ys, 'yhat': train_yhats},
                               'val': {'y': val_ys, 'yhat': val_yhats}},
                    'timer': sum(train_log['timer'])
                    }

        # Save
        torch.save(model.module.state_dict(), os.path.join(model_args['results_dir'], model_args['results_file'][:-4]+'_model.pt'))
        torch.save(best_log, os.path.join(model_args['results_dir'], model_args['results_file'][:-4]+'_stats.pt'))

    # Print
    print('Epoch {}\tTrain loss: {:.4f} Val loss: {:.4f} Train auc: {:.4f} Val auc: {:.4f} Time (min): {:.2f} Total time: {:.2f}'.format(
            epoch,
            train_log['loss']['train'][-1],
            train_log['loss']['val'][-1],
            train_log['auc']['train'][-1],
            train_log['auc']['val'][-1],
            epoch_time,
            sum(train_log['timer'])))

    if epoch - best_log['epoch'] > model_args['break_patience']:
        print('Breaking epoch loop')
        break

    # LR Scheduler step
    if model_args['scheduler_family'] == 'no-scheduler':
        pass
    elif model_args['scheduler_family'] == 'drop':
        scheduler.step(train_log['loss']['val'][-1])
    else:
        scheduler.step()

"""Post train"""
epoch = best_log['epoch']
train_loss = best_log['loss']['train']
val_loss = best_log['loss']['val']
val_auc = best_log['auc']['val']

results = {
    'File': model_args['results_file'],
    'Architecture': model_args['model_type'],
    '% Data': model_args['train_file'][model_args['train_file'].rfind('_') + 1:model_args['train_file'].rfind('.')],
    'Initial LR': model_args['initial_lr'],
    'Optimizer': model_args['optimizer_family'],
    'Scheduler': model_args['scheduler_family'],
    'Scheduler Patience': model_args['plateau_patience'],
    'Break Patience': model_args['break_patience'],
    'Scheduler Drop Factor': model_args['drop_factor'],
    'Batch Size': model_args['batch_size'],
    'Weight Decay': model_args['weight_decay'],
    'Frozen': model_args['frozen'],
    'Mixup': model_args['use_mixup'],
    'Transform': model_args['train_transform'],
    'Norm Layer': model_args['norm_layer'],
    'Dropout': model_args['dropout'],
    'Fold': model_args['fold'],
    'Epoch': epoch,
    'Loss Train': train_loss,
    'Loss Val': val_loss,
    'AUC Val': val_auc,
    'Total Time': best_log['timer']
}

print(','.join([str(x) for x in results.values()]))
printToResults(','.join([str(x) for x in results.values()])+'\n', os.path.join(model_args['results_dir'],'results.csv'))
