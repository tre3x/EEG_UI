# backend/inference.py
import torch
import numpy as np
from .gru import GRUModel, standardize  # Adjust imports if needed.
# If you want to support LSTM, you can also import it:
# from lstm import LSTMModel

# Optionally, if you want to use a bandpass filter, uncomment the following line:
# from utils import bandpass_filter

class EEGModelInference:
    def __init__(self, model_path, model_type='gru', device='cuda'):
        self.device = device
        if model_type.lower() == 'gru':
            self.model = GRUModel(input_size=1, hidden_size=64, output_size=1, num_layers=2).to(device)
        elif model_type.lower() == 'lstm':
            # from lstm import LSTMModel  # uncomment if using LSTM
            self.model = LSTMModel(input_size=1, hidden_size=128, output_size=1, num_layers=1).to(device)
        else:
            raise ValueError("Unsupported model type")
        # Load the model's saved state dictionary
        self.model.load_state_dict(torch.load(model_path, map_location=device))
        self.model.eval()

    def predict_windows(self, windows, batch_size=32):
        """
        Given a NumPy array of windows (shape: [num_windows, window_length]),
        apply pre-processing and then use the loaded model to predict each window.
        Returns a list of string labels for each window.
        """
        # If you need to apply a bandpass filter, uncomment the line below
        # windows = bandpass_filter(windows, lowcut=0.5, highcut=60, fs=256)
        
        # Standardize the windows using your custom standardize function.
        windows_std = standardize(windows)
        # Add the feature dimension (e.g., channel dimension) so the input shape becomes (N, L, 1)
        windows_std = windows_std[..., np.newaxis]
        
        # Convert to a Torch tensor
        windows_tensor = torch.tensor(windows_std, dtype=torch.float32).to(self.device)
        predictions = []
        num_windows = windows_tensor.shape[0]
        
        # Process in batches to avoid GPU memory issues
        with torch.inference_mode():
            for i in range(0, num_windows, batch_size):
                batch = windows_tensor[i:i+batch_size]
                # Assuming your model outputs a probability (or a value between 0 and 1)
                outputs = self.model(batch)
                # Remove any extra dimensions if necessary
                outputs = outputs.squeeze()
                # Threshold at 0.5 to decide between "Seizure" and "Non-Seizure"
                # (Adjust the threshold if your model uses a different decision boundary.)
                batch_preds = (outputs > 0.5).cpu().numpy()
                # Convert the boolean predictions to string labels
                batch_labels = ["Seizure" if pred else "Non-Seizure" for pred in batch_preds]
                predictions.extend(batch_labels)

        return predictions

# Initialize a global instance of the inference engine
# (Make sure to update the model_save_path to your actual model file.)
MODEL_SAVE_PATH = "/Users/shreyanganguly/Python/EEG_detect/models_animal/RN197-23/gru_model_epoch_40.pth"
device = 'cuda' if torch.cuda.is_available() else 'cpu'
eeg_inference = EEGModelInference(model_path=MODEL_SAVE_PATH, model_type='gru', device=device)
