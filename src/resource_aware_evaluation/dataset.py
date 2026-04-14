import torch
from torch.utils.data import Dataset
from torch.nn.utils.rnn import pad_sequence
import json
import os
import math
from collections import Counter

class DASHDataset(Dataset):
    def __init__(self, jsonl_paths, vocab=None, max_len=512):
        self.data = []
        self.max_len = max_len
        
        # handle single string path
        if isinstance(jsonl_paths, str):
            jsonl_paths = [jsonl_paths]
            
        print(f"Loading data from {len(jsonl_paths)} files...")
        
        for path in jsonl_paths:
            if not os.path.exists(path):
                print(f"File not found {path}")
                continue
                
            print(f"  -> Reading {os.path.basename(path)} ...")
            count = 0
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        self.data.append(json.loads(line))
                        count += 1
                    except:
                        continue
            print(f"     Loaded {count} samples.")

        print(f"Total samples loaded: {len(self.data)}")

        # build vocab if not provided
        if vocab is None:
            self.vocab = self.build_vocab()
        else:
            self.vocab = vocab


    def build_vocab(self, min_freq=1):
        print("Building vocabulary...")
        counter = Counter()
        for item in self.data:
            tokens = item['input_sequence']['tokens']
            counter.update(tokens)
        
        # 0: PAD, 1: UNK
        vocab = {"<PAD>": 0, "<UNK>": 1}
        for token, freq in counter.items():
            if freq >= min_freq:
                vocab[token] = len(vocab)
        print(f"Vocabulary size: {len(vocab)}")
        return vocab

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]
        seq = item['input_sequence']
        
        # tokens to IDs
        tokens = seq['tokens']
        token_ids = [self.vocab.get(t, self.vocab["<UNK>"]) for t in tokens]
        
        # truncate sequence if it exceeds max_len
        if len(token_ids) > self.max_len:
            token_ids = token_ids[:self.max_len]
            for key in ['bitwidths', 'phy_types', 'signed_flags', 'target_mask', 'dependency_mask', 'fanout_mask']:
                if isinstance(seq[key], list):
                    seq[key] = seq[key][:self.max_len]

        # to tensors
        token_ids = torch.tensor(token_ids, dtype=torch.long)
        bitwidths = torch.tensor(seq['bitwidths'], dtype=torch.float32).unsqueeze(-1) # [L, 1]
        phy_types = torch.tensor(seq['phy_types'], dtype=torch.long)
        signed_flags = torch.tensor(seq['signed_flags'], dtype=torch.float32).unsqueeze(-1)
        
        # sequence masks
        target_mask = torch.tensor(seq['target_mask'], dtype=torch.float32)
        dependency_mask = torch.tensor(seq.get('dependency_mask', [0]*len(token_ids)), dtype=torch.float32)
        fanout_mask = torch.tensor(seq.get('fanout_mask', [0]*len(token_ids)), dtype=torch.float32)

        # explicit global features
        explicit = seq['explicit_features']
        bw_prod = math.log1p(explicit.get('operand_bw_product', 0.0))
        explicit_feat = torch.tensor([bw_prod], dtype=torch.float32)

        # apply signed log1p to labels for long-tail distribution
        labels = item['labels']
        area_gain = labels['area_gain']
        delay_gain = labels['delay_gain']
        
        def signed_log(x):
            return math.copysign(math.log1p(abs(x)), x)

        label_tensor = torch.tensor([
            signed_log(area_gain), 
            signed_log(delay_gain)
        ], dtype=torch.float32)

        return {
            "token_ids": token_ids,
            "bitwidths": bitwidths,
            "phy_types": phy_types,
            "signed_flags": signed_flags,
            "target_mask": target_mask,
            "dependency_mask": dependency_mask,
            "fanout_mask": fanout_mask,
            "explicit_features": explicit_feat,
            "labels": label_tensor
        }

def pad_collate_fn(batch):
    batch_out = {}
    
    token_ids = [b['token_ids'] for b in batch]
    bitwidths = [b['bitwidths'] for b in batch]
    phy_types = [b['phy_types'] for b in batch]
    signed_flags = [b['signed_flags'] for b in batch]
    target_masks = [b['target_mask'] for b in batch]
    dep_masks = [b['dependency_mask'] for b in batch]
    fanout_masks = [b['fanout_mask'] for b in batch]
    
    # pad sequences
    batch_out['token_ids'] = pad_sequence(token_ids, batch_first=True, padding_value=0)
    batch_out['phy_types'] = pad_sequence(phy_types, batch_first=True, padding_value=5) # 5 = OTHER
    
    batch_out['bitwidths'] = pad_sequence(bitwidths, batch_first=True, padding_value=0)
    batch_out['signed_flags'] = pad_sequence(signed_flags, batch_first=True, padding_value=0)
    batch_out['target_mask'] = pad_sequence(target_masks, batch_first=True, padding_value=0)
    batch_out['dependency_mask'] = pad_sequence(dep_masks, batch_first=True, padding_value=0)
    batch_out['fanout_mask'] = pad_sequence(fanout_masks, batch_first=True, padding_value=0)
    
    batch_out['explicit_features'] = torch.stack([b['explicit_features'] for b in batch])
    batch_out['labels'] = torch.stack([b['labels'] for b in batch])
    
    # generate padding mask
    batch_out['padding_mask'] = (batch_out['token_ids'] == 0)
    
    return batch_out