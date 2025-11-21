# ToCaro-Raspberry-Pi

#### Funktionsweise

Das Seil wird über einen Getriebemotor auf eine Seilwinde aufgezogen (siehe CAD-Modell). Die Regelung des Motors erfolgt dabei positionsgesteuert über Hall-Encoder die am Motor verbaut sind. Beim Drehen des Motors werden Rechtecksignale an den digitalen Input des Arduinos gesendet. Die Software kann dann die ausgelösten Flanken erkennen und so durch Zählen der Schritte die Position bestimmen. Die Ansteuerung des Motors erfolgt aktuell über das adafruit motor shield v2.3 welches mittels I2C mit dem Arduino verbunden ist. Auf dem shield sitzen drei chips, ein PCA9685 der das I2C Signal des Arduinos in PWM Signale Wandelt und zwei TB6612 MOSFETs die daraus die Spannung an die Motoren freigaben. Den aktuellen Code hab ich dir auf der nextcloud abgelegt. 

#### Ziel

Grundsätzlich soll erstmal alles so funktionieren wie es jetzt funktioniert, nur statt mit dem Arduino mit einem Raspberry Pi 5 betrieben werden. 
In einem ersten Schritt wäre es klasse, wenn du die Motorsteuerung über das Adafruit Motor Shield statt mit dem Arduino mit dem Pi laufen lässt. Dabei reicht es auch wenn erstmal ein Motor läuft.
Alex hat ein PCB designed auf dem (neben anderen Sachen) Power Delivery und die chips des motor shields drauf sind. Am Ende soll alles darüber laufen. Bis das da ist, denke ich du kannst ganz gut vorarbeiten wenn du nur den Arduino durch den PI ersetzt. Auf dem finalen Board sollte dann ja eigentlich alles genauso laufen :D  

#### Links zu den Bauteilen

Motor https://www.dfrobot.com/product-1436.html
Adafruit Motor Shield V2.3 https://www.adafruit.com/product/1438
PWM Chip auf dem Motor Shield PCA9685 https://www.digikey.de/de/htmldatasheets/production/1640697/0/0/1/pca9685-datasheet
TB6612 MOSFET auf dem Motor Shield https://www.digikey.de/en/products/detail/toshiba-semiconductor-and-storage/TB6612FNG-C-8-EL/1730070
