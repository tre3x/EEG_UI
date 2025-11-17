import torch.nn as nn



def standardize(data):
    return (data - data.mean(axis=1, keepdims=True)) / data.std(axis=1, keepdims=True)

class GRUModel(nn.Module):
    def __init__(self, input_size, hidden_size, output_size, num_layers=2, dropout=0.3):
        super(GRUModel, self).__init__()
        self.gru = nn.GRU(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_size, output_size)
        self.sigmoid = nn.Sigmoid()  # Binary classification activation

    def forward(self, x):
        _, h_n = self.gru(x)  # h_n: hidden state from the last GRU layer
        h_n = h_n[-1]  # Take the hidden state from the last layer
        out = self.fc(h_n)
        return self.sigmoid(out)