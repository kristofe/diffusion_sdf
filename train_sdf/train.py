#!/usr/bin/env python3

import torch
import torch.utils.data 
from torch.nn import functional as F
import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint, Callback, LearningRateMonitor
from pytorch_lightning import loggers as pl_loggers

import os
import json, csv
import time
from tqdm.auto import tqdm
from einops import rearrange, reduce
import numpy as np
import trimesh
import warnings

# add paths in model/__init__.py for new models
from models import * 
from utils import mesh, evaluate
from utils.reconstruct import *
from diff_utils.helpers import * 
#from metrics.evaluation_metrics import *#compute_all_metrics
#from metrics import evaluation_metrics

from dataloader.pc_loader import PCloader
from dataloader.sdf_loader import SdfLoader
from dataloader.modulation_loader import ModulationLoader


def train():
    
    # initialize dataset and loader
    split = json.load(open(specs["TrainSplit"], "r"))
    if specs['training_task'] == 'diffusion':
        train_dataset = ModulationLoader(specs["data_path"], pc_path=specs.get("pc_path",None), split_file=split, pc_size=specs.get("total_pc_size", None))
    else:
        train_dataset = SdfLoader(specs["DataSource"], split, pc_size=specs.get("PCsize",1024), grid_source=specs.get("GridSource", None), modulation_path=specs.get("modulation_path", None))
    train_dataloader = torch.utils.data.DataLoader(
            train_dataset,
            batch_size=args.batch_size, num_workers=args.workers,
            drop_last=True, shuffle=True, pin_memory=True, persistent_workers=True
        )

    # creates a copy of current code / files in the config folder
    save_code_to_conf(args.exp_dir) 
    
    # pytorch lightning callbacks 
    callback = ModelCheckpoint(dirpath=args.exp_dir, filename='{epoch}', save_top_k=-1, save_last=True, every_n_epochs=specs["log_freq"])
    lr_monitor = LearningRateMonitor(logging_interval='step')
    callbacks = [callback, lr_monitor]

    model = CombinedModel(specs)

    # note on loading from checkpoint:
    # if resuming from training modulation, diffusion, or end-to-end, just load saved checkpoint 
    # however, if fine-tuning end-to-end after training modulation and diffusion separately, will need to load checkpoint twice
    if args.resume == 'finetune':
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = model.load_from_checkpoint(specs["modulation_ckpt_path"], specs=specs, strict=False)
            #model = model.load_from_checkpoint(specs["diffusion_ckpt_path"], specs=specs, strict=False)
            ckpt = torch.load(specs["diffusion_ckpt_path"])
            model.diffusion_model.load_state_dict(ckpt['model_state_dict'])
        resume = None
    elif args.resume is not None:
        ckpt = "{}.ckpt".format(args.resume) if args.resume=='last' else "epoch={}.ckpt".format(args.resume)
        resume = os.path.join(args.exp_dir, ckpt)
    else:
        resume = None  

    # precision 16 can be unstable; recommend using 32
    trainer = pl.Trainer(gpus=-1, precision=32, max_epochs=specs["num_epochs"], callbacks=callbacks, log_every_n_steps=1,
                        default_root_dir=os.path.join("tensorboard_logs", args.exp_dir))
    trainer.fit(model=model, train_dataloaders=train_dataloader, ckpt_path=resume)

    

    
if __name__ == "__main__":

    import argparse

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument(
        "--exp_dir", "-e", #required=True,
        default='config/stage1_sdf/',
        help="This directory should include experiment specifications in 'specs.json,' and logging will be done in this directory as well.",
    )
    arg_parser.add_argument(
        "--resume", "-r", default=None,
        help="continue from previous saved logs, integer value, 'last', or 'finetune'",
    )

    # train SDF modulations, diffusion, or end-to-end
    # "training_task" in specs file
    # arg_parser.add_argument(
    #     "--mode", "-m", required=True,
    #     help="'modulation' or 'diffusion' or 'combined' ",
    # )

    # add argument for conditional training
    arg_parser.add_argument("--cond", "-c", default=False, action='store_true', help='False for unconditional training, True for conditional training')


    arg_parser.add_argument("--batch_size", "-b", default=1, type=int)
    arg_parser.add_argument( "--workers", "-w", default=8, type=int)





    arg_parser.add_argument("--test", "-t", action='store_true')
    arg_parser.add_argument("--latent", "-l", action='store_true')
    arg_parser.add_argument("--take_pc", "-p", default=False, nargs="+", help="path to the pc csv file")
    #arg_parser.add_argument("--take_mod", "-m", default=False, nargs="+", help="path to the modulation txt file")
    arg_parser.add_argument("--mod_folder", "-f", default=False, help="path to folder for reconstructing")
    #arg_parser.add_argument("--sample", "-s", action='store_true', help="true/false, sample from VAE")
    arg_parser.add_argument("--output_name", "-o", default=False, help="name of output ply file")
  
    args = arg_parser.parse_args()

    #just for debugging in VSCode 
    os.chdir("train_sdf")

    specs = json.load(open(os.path.join(args.exp_dir, "specs.json")))
    print(specs["Description"])

    train()


    # if args.mode == 'train':
    #     #assert args.train_mode in ('modulation', 'diffusion', 'combined'), "'train_mode' should be one of 'modulation', 'diffusion', 'combined'"
    #     train()
    # elif args.mode == 'test':
    #     test(args, specs)
    # elif args.mode == 'evaluate':
    #     evaluate(args, specs)
    # elif args.mode == 'visual':
    #     visualize(args, specs)
    # else:
    #     exit("The only modes available are 'train' 'test' 'evaluate' 'visual'...")






    save_dir = args.exp_dir
    recon_dir = os.path.join(save_dir, "recon")
    os.makedirs(save_dir, exist_ok=True)
    os.makedirs(recon_dir, exist_ok=True)
    latent_dir = os.path.join(save_dir, "modulations")
    os.makedirs(latent_dir, exist_ok=True)

    if args.test:
        test()
        exit()
 

