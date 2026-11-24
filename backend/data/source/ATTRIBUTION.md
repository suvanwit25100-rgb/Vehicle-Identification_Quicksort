# Data sources

- `vehicle_registrations_500k.csv` (not committed, 78 MB): "Indian Vehicle Registration Data (2020-25)" by Aatif Ahmad, Kaggle,
  https://www.kaggle.com/datasets/aatifahmad123/indian-vehicle-registration-data-202025, licence CC BY 4.0
  (https://creativecommons.org/licenses/by/4.0/). It holds aggregated registration counts, no plate numbers and no owners.
  Changes made: we sample its rows (weighted by vehicleCount) for state, RTO, maker, model, vehicle class and fuel, and attach random plates.
- `rto_codes_user.csv`: the team's RTO code list. Wikipedia's "List of Regional Transport Office districts in India" (CC BY-SA 4.0) fills gaps.
