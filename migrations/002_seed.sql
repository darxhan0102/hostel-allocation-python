INSERT INTO students (id, name, year, merit, room_type, floor_pref) VALUES
 -- A clean mutual pair, both near the top of the list.
 (1,'Aarav Mehta',      3, 9.40, 'double', 1),
 (2,'Bhavya Rao',       3, 9.10, 'double', 1),
 -- The chain. Ishita wants Janvi; Janvi wants Kabir; Kabir wants Janvi back.
 -- Ishita is going to be disappointed and the plan has to say why.
 (3,'Ishita Nair',      2, 8.90, 'double', 2),
 (4,'Janvi Kulkarni',   2, 8.70, 'double', 2),
 (5,'Kabir Shah',       2, 8.60, 'double', 2),
 -- A mutual triple who all asked for each other.
 (6,'Devansh Gupta',    4, 8.50, 'triple', 0),
 (7,'Eshan Pillai',     4, 8.30, 'triple', 0),
 (8,'Farhan Qureshi',   4, 8.20, 'triple', 0),
 -- Five mutually-agreed friends. The largest room holds four. One of them
 -- loses, and it must be the lowest-ranked of the five.
 (9, 'Gauri Deshpande', 1, 7.90, 'quad', 3),
 (10,'Harsh Vardhan',   1, 7.80, 'quad', 3),
 (11,'Lakshmi Iyer',    1, 7.70, 'quad', 3),
 (12,'Manan Joshi',     1, 7.60, 'quad', 3),
 (13,'Nikhil Bose',     1, 7.50, 'quad', 3),
 -- Two students with IDENTICAL merit and year. Only the id tiebreak separates
 -- them, which is exactly why merit_key has three components.
 (14,'Oviya Raman',     2, 7.20, 'single', 1),
 (15,'Pranav Sethi',    2, 7.20, 'single', 1),
 -- Singletons with no roommate requests at all.
 (16,'Qamar Ali',       3, 7.00, 'double', 0),
 (17,'Riya Chatterjee', 1, 6.80, 'double', 2),
 (18,'Sahil Dubey',     2, 6.50, 'triple', 3),
 (19,'Tanvi Menon',     1, 6.20, 'quad', 1),
 (20,'Umesh Kadam',     1, 5.90, 'quad', 2)
ON CONFLICT DO NOTHING;
SELECT setval('students_id_seq', GREATEST((SELECT MAX(id) FROM students),1));

INSERT INTO roommate_requests (student_id, wanted_id) VALUES
 -- mutual pair
 (1,2),(2,1),
 -- the chain: 3 -> 4 -> 5, and 5 -> 4. Only 4 and 5 are mutual.
 (3,4),(4,5),(5,4),
 -- mutual triple
 (6,7),(6,8),(7,6),(7,8),(8,6),(8,7),
 -- the five who cannot all fit in a quad
 (9,10),(9,11),(10,9),(10,11),(11,9),(11,12),(12,11),(12,13),(13,12),(13,9),
 -- a pair who both want each other but nothing else
 (14,15),(15,14)
ON CONFLICT DO NOTHING;

-- Deliberately not a tidy multiple of anything. There are 20 students and
-- 22 beds, so the plan is tight and the lonely-quad rule actually bites.
INSERT INTO rooms (id, code, block, floor, room_type, capacity) VALUES
 (1,'A-001','A',0,'triple',3),
 (2,'A-002','A',0,'triple',3),
 (3,'A-101','A',1,'double',2),
 (4,'A-102','A',1,'double',2),
 (5,'A-103','A',1,'single',1),
 (6,'B-201','B',2,'double',2),
 (7,'B-202','B',2,'double',2),
 (8,'B-203','B',2,'single',1),
 (9,'C-301','C',3,'quad',4),
 (10,'C-302','C',3,'quad',4)
ON CONFLICT DO NOTHING;
SELECT setval('rooms_id_seq', GREATEST((SELECT MAX(id) FROM rooms),1));
