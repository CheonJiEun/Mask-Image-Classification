import argparse
import glob
import json
import multiprocessing
import os
import random
import re
from importlib import import_module
from pathlib import Path
import wandb
import torchvision
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch.optim.lr_scheduler import StepLR, ReduceLROnPlateau, CosineAnnealingLR
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

from dataset import MaskBaseDataset, getDataloader, TestDataset
from loss import create_criterion
from sklearn.model_selection import StratifiedKFold

import pandas as pd
from torchvision.transforms import Resize, ToTensor, Normalize
import torch.nn as nn
from torch.optim import Adam
import wandb


def seed_everything(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)  # if use multi-GPU
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    np.random.seed(seed)
    random.seed(seed)


def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']


def grid_image(np_images, gts, preds, n=16, shuffle=False):
    batch_size = np_images.shape[0]
    assert n <= batch_size

    choices = random.choices(range(batch_size), k=n) if shuffle else list(range(n))
    figure = plt.figure(figsize=(12, 18 + 2))
    # cautions: hardcoded, 이미지 크기에 따라 figsize 를 조정해야 할 수 있습니다. T.T
    plt.subplots_adjust(top=0.8)  
    # cautions: hardcoded, 이미지 크기에 따라 top 를 조정해야 할 수 있습니다. T.T
    n_grid = int(np.ceil(n ** 0.5))
    
    
    tasks = ["mask", "gender", "age"]
    for idx, choice in enumerate(choices):
        gt = gts[choice].item()
        pred = preds[choice].item()
        image = np_images[choice]
        gt_decoded_labels = MaskBaseDataset.decode_multi_class(gt)
        pred_decoded_labels = MaskBaseDataset.decode_multi_class(pred)
        title = "\n".join([
            f"{task} - gt: {gt_label}, pred: {pred_label}"
            for gt_label, pred_label, task
            in zip(gt_decoded_labels, pred_decoded_labels, tasks)
        ])

        plt.subplot(n_grid, n_grid, idx + 1, title=title)
        plt.xticks([])
        plt.yticks([])
        plt.grid(False)
        plt.imshow(image, cmap=plt.cm.binary)

    return figure


def increment_path(path, exist_ok=False):
    """ Automatically increment path, i.e. runs/exp --> runs/exp0, runs/exp1 etc.

    Args:
        path (str or pathlib.Path): f"{model_dir}/{args.name}".
        exist_ok (bool): whether increment path (increment if False).
    """
    path = Path(path)
    if (path.exists() and exist_ok) or (not path.exists()):
        return str(path)
    else:
        dirs = glob.glob(f"{path}*")
        matches = [re.search(rf"%s(\d+)" % path.stem, d) for d in dirs]
        i = [int(m.groups()[0]) for m in matches if m]
        n = max(i) + 1 if i else 2
        return f"{path}{n}"

def rand_bbox(size):
    W = size[2]
    H = size[3]
    r = np.random.randint(2)
    cut_size = 0   # TODO : 얼마나 여백을 줘서 자를지? 0이면 5:5
    
    if r == 0:
        bbx1 = cut_size
        bby1 = W//2
        bbx2 = H-cut_size
        bby2 = W-cut_size
    else:
        bbx1 = cut_size
        bby1 = cut_size
        bbx2 = H-cut_size
        bby2 = W//2

    return bbx1, bby1, bbx2, bby2

        
def accuracy(output, target, topk=(1,)):
    """Computes the accuracy over the k top predictions for the specified values of k"""
    with torch.no_grad():
        maxk = max(topk)
        batch_size = target.size(0)

        _, pred = output.topk(maxk, 1, True, True)
        pred = pred.t()
        correct = pred.eq(target.view(1, -1).expand_as(pred))

        res = []
        for k in topk:
            correct_k = correct[:k].reshape(-1).float().sum(0, keepdim=True)
            res.append(correct_k.mul_(100.0 / batch_size))
        return res

def train(data_dir, model_dir, args):
    seed_everything(args.seed)
    
    save_dir = increment_path(os.path.join(model_dir, args.name))
    os.makedirs(save_dir, exist_ok=True)
    print('save_dir : ', save_dir)

    # -- settings
    use_cuda = torch.cuda.is_available()
    device = torch.device("cuda" if use_cuda else "cpu")

    # -- dataset
    dataset_module = getattr(import_module("dataset"), args.dataset)  # default: MaskBaseDataset
    dataset = dataset_module(
        data_dir=data_dir,
    )
    num_classes = dataset.num_classes  # 18

    # -- augmentation
    transform_module = getattr(import_module("dataset"), args.augmentation)  # default: BaseAugmentation
    transform = transform_module(
        resize=args.resize,
        mean=dataset.mean,
        std=dataset.std,
    )
    dataset.set_transform(transform)

    # -- data_loader
#     train_set, val_set = dataset.split_dataset()
    n_val = int(len(dataset) * args.val_ratio)
    n_train = len(dataset) - n_val
    train_set, val_set = torch.utils.data.random_split(dataset, [n_train, n_val])

    train_loader = DataLoader(
        train_set,
        batch_size=args.batch_size,
        num_workers=multiprocessing.cpu_count() // 2,
        shuffle=True,
        pin_memory=use_cuda,
        drop_last=True,
    )

    val_loader = DataLoader(
        val_set,
        batch_size=args.valid_batch_size,
        num_workers=multiprocessing.cpu_count() // 2,
        shuffle=False,
        pin_memory=use_cuda,
        drop_last=True,
    )

    counter = 0
    patience = 5
    accumulation_steps = 2
    best_val_acc = 0
    best_val_loss = np.inf


    # -- model
    model_module = getattr(import_module("model"), args.model)  # default: BaseModel
    model = model_module(
        num_classes=num_classes
    ).to(device)

    # -- loss & metric
    criterion1 = create_criterion(args.criterion)  # default: cross_entropy
    criterion2 = create_criterion(args.criterion, classes=2)  # default: cross_entropy
    criterion3 = create_criterion(args.criterion)  # default: cross_entropy
    
    opt_module = getattr(import_module("torch.optim"), args.optimizer)  # default: SGD
    optimizer = opt_module(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=args.lr,
        weight_decay=5e-4
    )
    scheduler = StepLR(optimizer, args.lr_decay_step, gamma=0.5)

    for epoch in range(args.epochs):
        # train loop
        model.train()
        loss_value = 0
        matches = 0
        train_loss = []
        for idx, train_batch in enumerate(train_loader):
            inputs, (mask_labels, gender_labels, age_labels) = train_batch
            inputs = inputs.to(device)
            mask_labels = mask_labels.to(device)
            gender_labels = gender_labels.to(device)
            age_labels = age_labels.to(device)
            
            if np.random.rand() < 0.8:
                optimizer.zero_grad()
                outs = model(inputs)
                (mask_outs, gender_outs, age_outs) = torch.split(outs, [3, 2, 3], dim=1)
                mask_loss = criterion1(mask_outs, mask_labels)
                gender_loss = criterion2(gender_outs, gender_labels)
                age_loss = criterion3(age_outs, age_labels)
                
                mask_preds = torch.argmax(mask_outs, dim = 1)
                gender_preds = torch.argmax(gender_outs, dim = 1)
                age_preds = torch.argmax(age_outs, dim = 1)
                
                loss = mask_loss + gender_loss + 1.5*age_loss
                
                loss.backward()
                optimizer.step()

                train_loss.append(loss.item())
            else:
                optimizer.zero_grad()
                rand_index = torch.randperm(inputs.size()[0])
                mask_outs_label_a = mask_labels
                mask_outs_label_b = mask_labels[rand_index]
                gender_outs_label_a = gender_labels
                gender_outs_label_b = gender_labels[rand_index]
                age_outs_label_a = age_labels
                age_outs_label_b = age_labels[rand_index]
                
                bbx1, bby1, bbx2, bby2 = rand_bbox(inputs.size())
                inputs[:, :, bbx1:bbx2, bby1:bby2] = inputs[rand_index, :, bbx1:bbx2, bby1:bby2]
                lam = 1 - ((bbx2 - bbx1) * (bby2 - bby1) / (inputs.size()[-1] * inputs.size()[-2]))
                
                outs = model(inputs)
                (mask_outs, gender_outs, age_outs) = torch.split(outs, [3, 2, 3], dim=1)
                
                mask_loss = criterion1(mask_outs, mask_outs_label_a)*lam+criterion1(mask_outs, mask_outs_label_b)*(1-lam)
                gender_loss = criterion2(gender_outs, gender_outs_label_a)*lam+criterion2(gender_outs, gender_outs_label_b)*(1-lam)
                age_loss = criterion3(gender_outs, age_outs_label_a)*lam+criterion3(gender_outs, age_outs_label_b)*(1-lam)
                
                loss = mask_loss + gender_loss + 1.5*age_loss
                
                loss.backward()
                optimizer.step()

                train_loss.append(loss.item())

            if (idx + 1) % args.log_interval == 0:
                train_loss_mean = np.mean(train_loss)
                current_lr = scheduler.get_last_lr()
                print(
                    f"Epoch[{epoch}/{args.epochs}]({idx + 1}/{len(train_loader)}) || "
                    f"training loss {train_loss_mean:4.4}"
                )
        # wandb 학습 단계에서 Loss, Accuracy 로그 저장
        wandb.log({
                "train_loss": train_loss_mean,
            })

        scheduler.step()
        

        # val loop
        with torch.no_grad():
            print("Calculating validation results...")
            model.eval()
            val_loss = []
            val_loss_items = []
            val_acc_items = []
            
            mask_loss_items = []
            gender_loss_items = []
            age_loss_items = []

            mask_val_acc_items = []
            gender_val_acc_items = []
            age_val_acc_items = []
            
            for val_batch in val_loader:
                inputs, (mask_labels, gender_labels, age_labels) = val_batch
                inputs = inputs.to(device)
                
                mask_labels = mask_labels.to(device)
                gender_labels = gender_labels.to(device)
                age_labels = age_labels.to(device)
                
                outs = model(inputs)

                mask_loss_item = criterion1(mask_outs, mask_labels).item()
                gender_loss_item = criterion2(gender_outs, gender_labels).item()
                age_loss_item = criterion3(age_outs, age_labels).item()
                loss_item = mask_loss_item + gender_loss_item + age_loss_item
                
                mask_preds = torch.argmax(mask_outs, dim = 1)
                gender_preds = torch.argmax(gender_outs, dim = 1)
                age_preds = torch.argmax(age_outs, dim = 1)
                
                preds, labels = dataset.encode_multi_class(mask_preds, gender_preds,age_preds), dataset.encode_multi_class(mask_labels, gender_labels, age_labels)
                mask_val_acc = (mask_labels == mask_preds).sum().item()
                gender_val_acc = (gender_labels == gender_preds).sum().item()
                age_val_acc = (age_labels == age_preds).sum().item()
                
                acc_item = (labels == preds).sum().item()
                val_loss_items.append(loss_item)
                val_acc_items.append(acc_item)

                mask_val_acc_items.append(mask_val_acc)
                gender_val_acc_items.append(gender_val_acc)
                age_val_acc_items.append(age_val_acc)

                mask_loss_items.append(mask_loss_item)
                gender_loss_items.append(gender_loss_item)
                age_loss_items.append(age_loss_item)
                
            mask_val_loss = np.sum(mask_loss_items) / len(val_loader)
            gender_val_loss = np.sum(gender_loss_items) / len(val_loader)
            age_val_loss = np.sum(age_loss_items) / len(val_loader)

            mask_val_acc = np.sum(mask_val_acc_items) / len(val_set)
            gender_val_acc = np.sum(gender_val_acc_items) / len(val_set)
            age_val_acc = np.sum(age_val_acc_items) / len(val_set)
            
            val_loss = np.mean(val_loss)
            val_acc = np.sum(val_acc_items) / len(val_set)
            
            # Callback1: validation accuracy가 향상될수록 모델을 저장합니다.
            if val_loss < best_val_loss:
                best_val_loss = val_loss
            if val_acc > best_val_acc:
                print(f"New best model for val accuracy : {val_acc:4.2%}! saving the best model..")
                torch.save(model.state_dict(), f"{save_dir}/best.pth")
                best_val_acc = val_acc
                counter = 0
            else:
                print(f"Not Update val accuracy... counter : {counter}")
                counter += 1
                
            torch.save(model.state_dict(), f"{save_dir}/last.pth")

            print(
                f"[Val] acc : {val_acc:4.2%}, loss: {val_loss:4.2} || "
                f"best acc : {best_val_acc:4.2%}, best loss: {best_val_loss:4.2}"
            )
            print()

            # wandb 검증 단계에서 Loss, Accuracy 로그 저장
            wandb.log({
                "valid_loss": val_loss,
                "valid_acc" : val_acc,
                "mask_loss" : mask_val_loss,
                "mask_acc" : mask_val_acc,
                "gender_loss" : gender_val_loss,
                "gender_acc" : gender_val_acc,
                "age_loss" : age_val_loss,
                "age_acc" : age_val_acc
            })
            # Callback2: patience 횟수 동안 성능 향상이 없을 경우 학습을 종료시킵니다.
            if counter > patience:
                print("Early Stopping...")
                break


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    # Data and model checkpoints directories
    parser.add_argument('--seed', type=int, default=42, help='random seed (default: 42)')
    parser.add_argument('--epochs', type=int, default=100, help='number of epochs to train (default: 1)')
    parser.add_argument('--dataset', type=str, default='MaskBaseDataset', help='dataset augmentation type (default: MaskBaseDataset)')
    parser.add_argument('--augmentation', type=str, default='BaseAugmentation', help='data augmentation type (default: BaseAugmentation)')
    parser.add_argument("--resize", nargs="+", type=int, default=[128, 96], help='resize size for image when training')
    parser.add_argument('--batch_size', type=int, default=64, help='input batch size for training (default: 64)')
    parser.add_argument('--valid_batch_size', type=int, default=1000, help='input batch size for validing (default: 1000)')
    parser.add_argument('--model', type=str, default='BaseModel', help='model type (default: BaseModel)')
    parser.add_argument('--optimizer', type=str, default='SGD', help='optimizer type (default: SGD)')
    parser.add_argument('--lr', type=float, default=1e-3, help='learning rate (default: 1e-3)')
    parser.add_argument('--val_ratio', type=float, default=0.2, help='ratio for validaton (default: 0.2)')
    parser.add_argument('--criterion', type=str, default='cross_entropy', help='criterion type (default: cross_entropy)')
    parser.add_argument('--lr_decay_step', type=int, default=20, help='learning rate scheduler deacy step (default: 20)')
    parser.add_argument('--log_interval', type=int, default=20, help='how many batches to wait before logging training status')
    parser.add_argument('--name', default='exp', help='model save at {SM_MODEL_DIR}/{name}')

    # Container environment
    parser.add_argument('--data_dir', type=str, default=os.environ.get('SM_CHANNEL_TRAIN', '/opt/ml/input/data/train/images'))
    parser.add_argument('--model_dir', type=str, default=os.environ.get('SM_MODEL_DIR', './model'))
    parser.add_argument('--output_dir', type=str, default=os.environ.get('SM_MODEL_DIR', './output'))

    args = parser.parse_args()
    
    wandb.init(project='wandb_test')
    wandb.config.update(args)
    wandb.run.name = 'cutmix'
    
    print(args)

    data_dir = args.data_dir
    model_dir = args.model_dir
    output_dir = args.output_dir
    
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    train(data_dir, model_dir, args)
