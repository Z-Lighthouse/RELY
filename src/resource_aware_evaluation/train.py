import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Subset
from tqdm import tqdm
import os
import numpy as np
import json
import pandas as pd
from sklearn.model_selection import KFold, train_test_split
from sklearn.metrics import r2_score, mean_absolute_error 
import warnings
import shutil
import sys
import datetime

warnings.filterwarnings("ignore", message="The PyTorch API of nested tensors is in prototype stage")

from dataset import DASHDataset, pad_collate_fn
from model import DASHModel


# experiment configuration
CONFIG = {
    "data_paths": [
        "./jsonl_files/one_dsp_whole.jsonl",
        "./jsonl_files/five_dsp_whole.jsonl"
    ],
    "batch_size": 32,
    "lr": 1e-4,
    "epochs": 50,
    "d_model": 256,
    "num_layers": 4,
    "nhead": 8,
    "device": "cuda" if torch.cuda.is_available() else "cpu",
    "save_dir": "./checkpoints_kfold",
    "seed": 42,
    "k_folds": 10
}


# duplicate stdout to a log file
class Logger(object):
    def __init__(self, logfile):
        self.terminal = sys.stdout
        self.log = open(logfile, "a", buffering=1)

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()


def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def get_metadata_from_dataset(dataset, idx):
    # default fallbacks
    meta_info = {
        "Meta_ID": "N/A",
        "Target_Line_Number": -1,
        "Source_File_Path": "N/A"
    }

    if hasattr(dataset, 'data') and idx < len(dataset.data):
        raw_item = dataset.data[idx]

        if isinstance(raw_item, str):
            try:
                raw_item = json.loads(raw_item)
            except:
                return meta_info

        if isinstance(raw_item, dict):
            meta_info["Meta_ID"] = raw_item.get("meta_id", "N/A")

            raw_text = raw_item.get("raw_text", {})
            if isinstance(raw_text, dict):
                meta_info["Target_Line_Number"] = raw_text.get("target_line_number", -1)
                meta_info["Source_File_Path"] = raw_text.get("file_path", "N/A")

    return meta_info


def train_k_fold():

    os.makedirs(CONFIG["save_dir"], exist_ok=True)

    # setup logging
    log_file = os.path.join(
        CONFIG["save_dir"],
        f"train_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    sys.stdout = Logger(log_file)
    sys.stderr = sys.stdout

    print("="*60)
    print("Experiment Start")
    print("Time:", datetime.datetime.now())
    print("Log File:", log_file)

    print("\nEnvironment Info")
    print("PyTorch:", torch.__version__)
    print("CUDA Available:", torch.cuda.is_available())

    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
        print("CUDA Version:", torch.version.cuda)

    print("Device:", CONFIG["device"])
    print("="*60)

    torch.manual_seed(CONFIG["seed"])
    np.random.seed(CONFIG["seed"])

    print("\n>>> Loading Full Dataset...")
    full_dataset = DASHDataset(CONFIG["data_paths"])
    dataset_len = len(full_dataset)

    print("Dataset Size:", dataset_len)
    print("Vocab Size:", len(full_dataset.vocab))

    if dataset_len == 0:
        print("Error: Dataset is empty.")
        return

    vocab_path = os.path.join(CONFIG["save_dir"], "vocab.json")
    if not os.path.exists(vocab_path):
        with open(vocab_path, 'w', encoding='utf-8') as f:
            json.dump(full_dataset.vocab, f, ensure_ascii=False, indent=2)

    print("\nTraining Config")
    print("Batch Size:", CONFIG["batch_size"])
    print("Epochs:", CONFIG["epochs"])
    print("LR:", CONFIG["lr"])
    print("K-Folds:", CONFIG["k_folds"])

    kf = KFold(n_splits=CONFIG["k_folds"], shuffle=True, random_state=CONFIG["seed"])

    global_results = []
    global_best_val_loss = float('inf')
    best_fold_idx = -1

    print(f"\n>>> Starting {CONFIG['k_folds']}-Fold Cross Validation on {CONFIG['device']}...")

    for fold_idx, (train_val_indices, test_indices) in enumerate(kf.split(range(dataset_len))):

        print(f"\n{'='*20} Fold {fold_idx + 1}/{CONFIG['k_folds']} {'='*20}")

        train_indices, val_indices = train_test_split(train_val_indices, test_size=0.1, random_state=CONFIG["seed"])

        train_loader = DataLoader(Subset(full_dataset, train_indices), batch_size=CONFIG["batch_size"], shuffle=True, collate_fn=pad_collate_fn)
        val_loader = DataLoader(Subset(full_dataset, val_indices), batch_size=CONFIG["batch_size"], shuffle=False, collate_fn=pad_collate_fn)
        test_loader = DataLoader(Subset(full_dataset, test_indices), batch_size=CONFIG["batch_size"], shuffle=False, collate_fn=pad_collate_fn)

        model = DASHModel(len(full_dataset.vocab), CONFIG["d_model"], CONFIG["nhead"], CONFIG["num_layers"]).to(CONFIG["device"])

        if fold_idx == 0:
            print("Model Parameters:", count_parameters(model))

        optimizer = optim.AdamW(model.parameters(), lr=CONFIG["lr"], weight_decay=1e-4)
        criterion = nn.MSELoss()

        current_fold_best_loss = float('inf')
        temp_weight_path = f"{CONFIG['save_dir']}/temp_fold_model.pth"

        for epoch in range(CONFIG["epochs"]):

            model.train()
            train_loss = 0

            pbar = tqdm(train_loader, desc=f"Fold {fold_idx+1} Ep {epoch+1}", leave=False)

            for batch in pbar:

                for k, v in batch.items():
                    if isinstance(v, torch.Tensor):
                        batch[k] = v.to(CONFIG["device"])

                optimizer.zero_grad()

                pred_area, pred_delay = model(batch)

                loss = criterion(pred_area, batch['labels'][:, 0].unsqueeze(-1)) + \
                       criterion(pred_delay, batch['labels'][:, 1].unsqueeze(-1))

                loss.backward()
                optimizer.step()

                train_loss += loss.item()

                pbar.set_postfix({"loss": f"{loss.item():.4f}"})

            model.eval()
            val_loss = 0

            with torch.no_grad():
                for batch in val_loader:

                    for k, v in batch.items():
                        if isinstance(v, torch.Tensor):
                            batch[k] = v.to(CONFIG["device"])

                    pred_area, pred_delay = model(batch)

                    val_loss += (
                        criterion(pred_area, batch['labels'][:, 0].unsqueeze(-1)) +
                        criterion(pred_delay, batch['labels'][:, 1].unsqueeze(-1))
                    ).item()

            avg_val_loss = val_loss / len(val_loader)

            print(f"  Fold {fold_idx+1} Ep {epoch+1}: Train={train_loss/len(train_loader):.4f}, Val={avg_val_loss:.4f}")

            if avg_val_loss < current_fold_best_loss:
                current_fold_best_loss = avg_val_loss
                torch.save(model.state_dict(), temp_weight_path)

        if current_fold_best_loss < global_best_val_loss:

            print(f"  >>> New Global Best Found! (Val Loss: {current_fold_best_loss:.4f})")

            global_best_val_loss = current_fold_best_loss
            best_fold_idx = fold_idx + 1

            shutil.copy(temp_weight_path, f"{CONFIG['save_dir']}/final_best_model.pth")

        model.load_state_dict(torch.load(temp_weight_path))
        model.eval()

        current_batch_start_idx = 0

        with torch.no_grad():

            for batch in tqdm(test_loader, desc="Predicting", leave=False):

                current_batch_size = batch['labels'].shape[0]

                batch_global_indices = test_indices[current_batch_start_idx: current_batch_start_idx + current_batch_size]

                current_batch_start_idx += current_batch_size

                for k, v in batch.items():
                    if isinstance(v, torch.Tensor):
                        batch[k] = v.to(CONFIG["device"])

                p_area, p_delay = model(batch)

                # inverse transform signed log1p to get actual values
                p_area_r = (torch.sign(p_area) * torch.expm1(torch.abs(p_area))).cpu().numpy().flatten()
                p_delay_r = (torch.sign(p_delay) * torch.expm1(torch.abs(p_delay))).cpu().numpy().flatten()

                t_area_r = (torch.sign(batch['labels'][:,0]) * torch.expm1(torch.abs(batch['labels'][:,0]))).cpu().numpy().flatten()
                t_delay_r = (torch.sign(batch['labels'][:,1]) * torch.expm1(torch.abs(batch['labels'][:,1]))).cpu().numpy().flatten()

                for i in range(len(p_area_r)):

                    global_idx = batch_global_indices[i]

                    meta = get_metadata_from_dataset(full_dataset, global_idx)

                    global_results.append({

                        "Meta_ID": meta["Meta_ID"],
                        "Target_Line_Num": meta["Target_Line_Number"],
                        "Source_File_Path": meta["Source_File_Path"],
                        "Global_Index": global_idx,

                        "True_Area": int(round(t_area_r[i])),
                        "Pred_Area": p_area_r[i],
                        "True_Delay": int(round(t_delay_r[i])),
                        "Pred_Delay": p_delay_r[i]
                    })

        if os.path.exists(temp_weight_path):
            os.remove(temp_weight_path)

    print("\n" + "="*40)
    print(f"Final Best Model from Fold {best_fold_idx} saved.")
    print("="*40)

    df = pd.DataFrame(global_results)

    df["True_Area"] = df["True_Area"].astype(int)
    df["True_Delay"] = df["True_Delay"].astype(int)

    df["Pred_Product"] = df["Pred_Area"] * df["Pred_Delay"]
    df["True_Product"] = df["True_Area"] * df["True_Delay"]

    # overall metrics evaluation
    r2_area = r2_score(df["True_Area"], df["Pred_Area"])
    r2_delay = r2_score(df["True_Delay"], df["Pred_Delay"])
    mae_area = mean_absolute_error(df["True_Area"], df["Pred_Area"])
    mae_delay = mean_absolute_error(df["True_Delay"], df["Pred_Delay"])

    print("-" * 30)
    print(f"Overall Metrics (Average over {CONFIG['k_folds']} folds):")
    print(f"  Area Gain:")
    print(f"    R2 Score: {r2_area:.4f}")
    print(f"    MAE:      {mae_area:.4f}")
    print(f"  Delay Gain (Level):")
    print(f"    R2 Score: {r2_delay:.4f}")
    print(f"    MAE:      {mae_delay:.4f}")
    print("-" * 30)

    print("\nExperiment Finished")
    print("End Time:", datetime.datetime.now())

if __name__ == "__main__":
    train_k_fold()