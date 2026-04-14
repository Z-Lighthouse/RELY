import torch
import torch.nn as nn
import math

class ContextAwareEmbedding(nn.Module):
    def __init__(self, vocab_size, d_model, max_len=1024):
        super().__init__()
        
        # base token embedding
        self.token_emb = nn.Embedding(vocab_size, d_model)
        
        # physical features mapped via MLP
        self.bw_emb = nn.Sequential(
            nn.Linear(1, d_model // 2), nn.ReLU(), nn.Linear(d_model // 2, d_model)
        )
        self.signed_emb = nn.Sequential(
            nn.Linear(1, d_model // 4), nn.ReLU(), nn.Linear(d_model // 4, d_model)
        )
        self.type_emb = nn.Embedding(6, d_model) # assuming 6 types
        
        # contextual mask embeddings (map 0.0, 0.5, 1.0 to d_model)
        self.target_highlight = nn.Linear(1, d_model)      
        self.dep_highlight = nn.Linear(1, d_model)         
        self.fanout_highlight = nn.Linear(1, d_model)      

        # positional encoding
        self.pos_emb = nn.Embedding(max_len, d_model)
        
        self.norm = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(0.1)

    def forward(self, batch):
        tokens = batch['token_ids']
        L = tokens.size(1)
        device = tokens.device
        
        # aggregate base features
        x = self.token_emb(tokens)
        
        # ensure dims match [B, L, 1]
        bw = batch['bitwidths'].unsqueeze(-1) if batch['bitwidths'].dim() == 2 else batch['bitwidths']
        sgn = batch['signed_flags'].unsqueeze(-1) if batch['signed_flags'].dim() == 2 else batch['signed_flags']
        
        x = x + self.bw_emb(bw)
        x = x + self.type_emb(batch['phy_types'])
        x = x + self.signed_emb(sgn)
        
        # add context masks
        t_mask = batch['target_mask'].unsqueeze(-1)
        d_mask = batch['dependency_mask'].unsqueeze(-1)
        f_mask = batch['fanout_mask'].unsqueeze(-1)
        
        x = x + self.target_highlight(t_mask)
        x = x + self.dep_highlight(d_mask)
        x = x + self.fanout_highlight(f_mask)
        
        # add pos encoding
        positions = torch.arange(L, device=device).unsqueeze(0)
        x = x + self.pos_emb(positions)
        
        return self.dropout(self.norm(x))

class DASHModel(nn.Module):
    def __init__(self, vocab_size, d_model=256, nhead=8, num_layers=4):
        super().__init__()
        
        self.embedding = ContextAwareEmbedding(vocab_size, d_model)
        
        # transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead, batch_first=True)
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        # explicit feature projection (maps 1D feature to d_model)
        self.explicit_proj = nn.Sequential(
            nn.Linear(1, d_model // 2),      
            nn.ReLU(),
            nn.Linear(d_model // 2, d_model),
            nn.LayerNorm(d_model),           
            nn.Dropout(0.1)
        )

        # prediction heads
        # input dim = transformer out (d_model) + explicit feature emb (d_model)
        final_input_dim = d_model * 2  
        
        self.area_head = nn.Sequential(
            nn.Linear(final_input_dim, 256), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(256, 64), nn.ReLU(),
            nn.Linear(64, 1)
        )
        
        self.delay_head = nn.Sequential(
            nn.Linear(final_input_dim, 256), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(256, 64), nn.ReLU(),
            nn.Linear(64, 1)
        )

    def forward(self, batch):
        x = self.embedding(batch) 
        
        # encode with padding mask
        x = self.encoder(x, src_key_padding_mask=batch['padding_mask'])
        
        # weighted pooling on target mask
        weights = batch['target_mask'].unsqueeze(-1)
        
        sum_features = torch.sum(x * weights, dim=1) 
        sum_weights = torch.sum(weights, dim=1) + 1e-9
        pooled_feat = sum_features / sum_weights # [B, d_model]
        
        # process explicit features (log1p to compress value range)
        raw_explicit = batch['explicit_features']
        log_explicit = torch.log1p(raw_explicit)
        
        explicit_emb = self.explicit_proj(log_explicit)
        
        # concat pooled features and explicit embeddings -> [B, 512]
        final_input = torch.cat([pooled_feat, explicit_emb], dim=1)
        
        area_pred = self.area_head(final_input)
        delay_pred = self.delay_head(final_input)
        
        return area_pred, delay_pred

# Sanity check
if __name__ == "__main__":
    # dummy params
    BATCH_SIZE = 4
    SEQ_LEN = 10
    VOCAB_SIZE = 100
    D_MODEL = 256
    
    model = DASHModel(vocab_size=VOCAB_SIZE, d_model=D_MODEL)
    
    # dummy batch
    dummy_batch = {
        'token_ids': torch.randint(0, VOCAB_SIZE, (BATCH_SIZE, SEQ_LEN)),
        'bitwidths': torch.rand(BATCH_SIZE, SEQ_LEN, 1) * 32,
        'phy_types': torch.randint(0, 6, (BATCH_SIZE, SEQ_LEN)),
        'signed_flags': torch.randint(0, 2, (BATCH_SIZE, SEQ_LEN)).float().unsqueeze(-1),
        'target_mask': torch.randint(0, 2, (BATCH_SIZE, SEQ_LEN)).float(), 
        'dependency_mask': torch.rand(BATCH_SIZE, SEQ_LEN), 
        'fanout_mask': torch.rand(BATCH_SIZE, SEQ_LEN),
        'padding_mask': torch.zeros(BATCH_SIZE, SEQ_LEN).bool(), 
        # operand bitwidth product, e.g., 32*32=1024
        'explicit_features': torch.rand(BATCH_SIZE, 1) * 1024 
    }
    
    # forward pass
    area, delay = model(dummy_batch)
    
    print("Success！")
    print(f"Explicit Feature Raw Shape: {dummy_batch['explicit_features'].shape}")
    print(f"Output Area Shape: {area.shape}")   # expected [4, 1]
    print(f"Output Delay Shape: {delay.shape}") # expected [4, 1]